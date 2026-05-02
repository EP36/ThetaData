"""Coinbase Advanced Trade execution layer.

Provides:
  should_trade_spot  — fee-aware edge/risk gate (pure logic, no I/O)
  place_market_order — submit a market IOC order with full risk controls

Design principles:
  - Never retry after a rejection to avoid runaway duplicate orders.
  - Every order produces a TradeRecord, even failed ones.
  - All monetary constants come from BasisConfig, not magic numbers here.
  - Side-effect free should_trade_spot makes it easy to unit-test.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Literal

from theta.config.basis import BasisConfig
from theta.telemetry.trade_log import TradeRecord, log_trade

LOGGER = logging.getLogger("theta.execution.coinbase")


class ExecutionError(RuntimeError):
    """Raised when an order cannot be placed (API error, rejection, etc.)."""


# ---------------------------------------------------------------------------
# Edge / risk gate
# ---------------------------------------------------------------------------

def should_trade_spot(
    asset: str,
    notional_usd: float,
    expected_edge_bps: float,
    config: BasisConfig,
) -> tuple[bool, str]:
    """Determine whether a spot trade meets ROI and risk thresholds.

    Pure function — no I/O, no side effects.  Returns (decision, reason)
    where reason is always a loggable structured string explaining the outcome.

    The hurdle is:
        round_trip_cost_bps + min_edge_bps
      = 2 * (cb_taker_fee_bps + slippage_buffer_bps) + min_edge_bps

    With defaults (60 + 5) * 2 + 20 = 150 bps required alpha to trade.

    Args:
        asset:             Base currency (used only for logging).
        notional_usd:      Intended trade size in USD.
        expected_edge_bps: Caller's alpha estimate in bps (0 = no signal).
        config:            BasisConfig instance with fee/risk params.

    Returns:
        (True,  reason_string)  if the trade should proceed.
        (False, reason_string)  if any check fails.
    """
    # --- Size limits ---
    if notional_usd < config.min_notional_usd:
        return False, (
            f"notional_too_small notional={notional_usd:.2f} "
            f"min={config.min_notional_usd:.2f}"
        )
    if notional_usd > config.max_notional_usd:
        return False, (
            f"notional_too_large notional={notional_usd:.2f} "
            f"max={config.max_notional_usd:.2f}"
        )

    # --- Edge vs cost hurdle ---
    hurdle = config.hurdle_bps
    if expected_edge_bps < hurdle:
        return False, (
            f"edge_below_hurdle "
            f"expected={expected_edge_bps:.1f}bps "
            f"hurdle={hurdle:.1f}bps "
            f"[fees={config.cb_taker_fee_bps:.1f}bps×2 "
            f"slippage={config.slippage_buffer_bps:.1f}bps×2 "
            f"margin={config.min_edge_bps:.1f}bps]"
        )

    net_bps = expected_edge_bps - config.round_trip_cost_bps
    return True, (
        f"edge_sufficient "
        f"expected={expected_edge_bps:.1f}bps "
        f"hurdle={hurdle:.1f}bps "
        f"net_after_costs={net_bps:.1f}bps "
        f"notional={notional_usd:.2f}"
    )


# ---------------------------------------------------------------------------
# Order placement
# ---------------------------------------------------------------------------

def place_market_order(
    asset: str,
    side: Literal["buy", "sell"],
    notional_usd: float,
    quote: str = "USD",
    expected_edge_bps: float = 0.0,
    config: BasisConfig | None = None,
    dry_run: bool = False,
) -> TradeRecord:
    """Submit a market IOC order on Coinbase Advanced Trade.

    Computes expected cost before placing, then logs the full execution context.
    Never retries — if the API rejects, raises ExecutionError immediately.

    Args:
        asset:              Base currency, e.g. "ETH".
        side:               "buy" or "sell".
        notional_usd:       For buy:  amount of quote (USD) to spend.
                            For sell: we compute base_size from mid_price.
        quote:              Quote currency (default "USD").
        expected_edge_bps:  Alpha estimate for this trade (for telemetry).
        config:             BasisConfig — uses defaults if None.
        dry_run:            If True, builds the full record and logs but
                            does not call create_order.

    Returns:
        TradeRecord with status="submitted" (live) or "dry_run".

    Raises:
        ExecutionError: on API error or order rejection.
        MarketDataError: if mid_price cannot be fetched (re-raised).
    """
    cfg = config or BasisConfig.from_env()

    # Fetch mid price for cost estimation (also validates connectivity)
    from theta.marketdata.coinbase import get_spot_mid_price
    mid_price = get_spot_mid_price(asset, quote)

    # Build cost estimates
    expected_fee_usd      = notional_usd * cfg.cb_taker_fee_bps   / 10_000.0
    expected_slippage_usd = notional_usd * cfg.slippage_buffer_bps / 10_000.0
    expected_total_cost   = expected_fee_usd + expected_slippage_usd

    product_id      = f"{asset}-{quote}"
    client_order_id = f"trauto-spot-{int(time.time() * 1000)}"
    timestamp       = TradeRecord.make_timestamp()

    LOGGER.info(
        "coinbase_order_preflight product=%s side=%s notional=%.2f "
        "mid=%.6f exp_fee=%.4f exp_slip=%.4f exp_cost=%.4f "
        "edge=%.1fbps dry_run=%s client_oid=%s",
        product_id, side, notional_usd,
        mid_price, expected_fee_usd, expected_slippage_usd, expected_total_cost,
        expected_edge_bps, dry_run, client_order_id,
    )

    if dry_run:
        record = TradeRecord(
            timestamp=timestamp,
            exchange="coinbase",
            asset=asset,
            quote=quote,
            side=side,
            notional_usd=notional_usd,
            expected_edge_bps=expected_edge_bps,
            mid_price_at_order=mid_price,
            expected_fee_usd=expected_fee_usd,
            expected_slippage_usd=expected_slippage_usd,
            expected_total_cost_usd=expected_total_cost,
            order_id="",
            client_order_id=client_order_id,
            status="dry_run",
        )
        log_trade(record, cfg.log_dir)
        return record

    # --- Live order ---
    cb = _require_client()

    if side == "buy":
        order_config = {
            "market_market_ioc": {"quote_size": f"{notional_usd:.2f}"}
        }
    else:
        # sell: convert notional → base size using current mid_price
        base_size = notional_usd / mid_price
        order_config = {
            "market_market_ioc": {"base_size": f"{base_size:.8f}"}
        }

    try:
        resp = cb.create_order(
            client_order_id=client_order_id,
            product_id=product_id,
            side=side.upper(),
            order_configuration=order_config,
        )
    except Exception as exc:
        # Surface the raw error immediately — no retry
        LOGGER.error(
            "coinbase_order_api_error product=%s side=%s "
            "notional=%.2f error=%s",
            product_id, side, notional_usd, exc,
        )
        record = TradeRecord(
            timestamp=timestamp,
            exchange="coinbase",
            asset=asset,
            quote=quote,
            side=side,
            notional_usd=notional_usd,
            expected_edge_bps=expected_edge_bps,
            mid_price_at_order=mid_price,
            expected_fee_usd=expected_fee_usd,
            expected_slippage_usd=expected_slippage_usd,
            expected_total_cost_usd=expected_total_cost,
            order_id="",
            client_order_id=client_order_id,
            status="failed",
            error=str(exc),
        )
        log_trade(record, cfg.log_dir)
        raise ExecutionError(
            f"create_order_api_error product={product_id} "
            f"side={side} notional={notional_usd:.2f} error={exc}"
        ) from exc

    # Parse the SDK response
    success = getattr(resp, "success", False)
    if not success:
        failure = (
            getattr(resp, "failure_reason", None)
            or str(getattr(resp, "error_response", "unknown"))
        )
        LOGGER.error(
            "coinbase_order_rejected product=%s side=%s "
            "notional=%.2f reason=%s",
            product_id, side, notional_usd, failure,
        )
        record = TradeRecord(
            timestamp=timestamp,
            exchange="coinbase",
            asset=asset,
            quote=quote,
            side=side,
            notional_usd=notional_usd,
            expected_edge_bps=expected_edge_bps,
            mid_price_at_order=mid_price,
            expected_fee_usd=expected_fee_usd,
            expected_slippage_usd=expected_slippage_usd,
            expected_total_cost_usd=expected_total_cost,
            order_id="",
            client_order_id=client_order_id,
            status="rejected",
            error=str(failure),
        )
        log_trade(record, cfg.log_dir)
        raise ExecutionError(
            f"order_rejected product={product_id} reason={failure}"
        )

    # Extract order_id from success_response
    order_id = (
        getattr(resp, "order_id", "")
        or getattr(getattr(resp, "success_response", None), "order_id", "")
        or ""
    )

    LOGGER.info(
        "coinbase_order_placed product=%s side=%s notional=%.2f "
        "mid=%.6f order_id=%s client_oid=%s",
        product_id, side, notional_usd, mid_price, order_id, client_order_id,
    )

    record = TradeRecord(
        timestamp=timestamp,
        exchange="coinbase",
        asset=asset,
        quote=quote,
        side=side,
        notional_usd=notional_usd,
        expected_edge_bps=expected_edge_bps,
        mid_price_at_order=mid_price,
        expected_fee_usd=expected_fee_usd,
        expected_slippage_usd=expected_slippage_usd,
        expected_total_cost_usd=expected_total_cost,
        order_id=order_id,
        client_order_id=client_order_id,
        status="submitted",
    )
    log_trade(record, cfg.log_dir)
    return record


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_client():
    from funding_arb.coinbase_client import get_coinbase_client
    cb = get_coinbase_client()
    if cb is None:
        raise ExecutionError(
            "coinbase_client_unavailable — "
            "check COINBASE_API_KEY and COINBASE_API_SECRET"
        )
    return cb
