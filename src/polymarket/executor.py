"""Execution engine — places orders on the Polymarket CLOB API.

Gated behind RiskGuard. POLY_DRY_RUN=true (default) logs intent only.
Never modifies Alpaca files or any other broker integration.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from src.polymarket.config import PolymarketConfig
from src.polymarket.opportunities import Opportunity
from src.polymarket.positions import PositionsLedger, new_position
from src.polymarket.risk import RiskGuard

LOGGER = logging.getLogger("theta.polymarket.executor")

# Only orderbook_spread is fully executable on Polymarket alone in Phase 2.
# cross_market requires Kalshi API (Phase 3).
# correlated_markets requires two-market coordination (Phase 3).
_EXECUTABLE_STRATEGIES = {"orderbook_spread"}


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Outcome of a single execute() call."""

    success: bool
    order_id: str = ""
    fill_price: float = 0.0
    size_usdc: float = 0.0
    error: str = ""


# ---------------------------------------------------------------------------
# Low-level order placement (live mode only)
# ---------------------------------------------------------------------------

def _place_order(
    config: PolymarketConfig,
    token_id: str,
    size_usdc: float,
    price: float,
    side: str,  # "BUY" | "SELL"
) -> dict[str, Any]:
    """Build, sign, and POST a GTC limit order via py-clob-client.

    Requires `pip install py-clob-client` for live execution.
    Retries up to config.max_retries times on transient network errors.
    Raises RuntimeError on auth/funding failures (non-retryable).
    """
    try:
        from py_clob_client.client import ClobClient as _PyClobClient  # type: ignore[import]
        from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType  # type: ignore[import]
        from py_clob_client.order_builder.constants import BUY, SELL  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "py-clob-client is required for live order execution. "
            "Install it with: pip install 'py-clob-client>=0.7'"
        ) from exc

    py_client = _PyClobClient(
        host=config.clob_base_url,
        key=config.private_key,
        chain_id=137,  # Polygon mainnet
        creds=ApiCreds(
            api_key=config.api_key,
            api_secret=config.api_secret,
            api_passphrase=config.passphrase,
        ),
    )

    py_side = BUY if side.upper() == "BUY" else SELL
    size_tokens = size_usdc / price  # USDC amount → number of outcome tokens

    last_exc: Exception | None = None
    for attempt in range(config.max_retries + 1):
        if attempt > 0:
            sleep_sec = 2 ** (attempt - 1)
            LOGGER.debug(
                "polymarket_order_retry attempt=%d token_id=%s sleep_sec=%d",
                attempt,
                token_id,
                sleep_sec,
            )
            time.sleep(sleep_sec)

        try:
            signed = py_client.create_order(
                OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=size_tokens,
                    side=py_side,
                )
            )
            LOGGER.debug(
                "polymarket_order_placing token_id=%s side=%s price=%.4f "
                "size_usdc=%.2f size_tokens=%.4f",
                token_id,
                side,
                price,
                size_usdc,
                size_tokens,
            )
            resp: dict[str, Any] = py_client.post_order(signed, OrderType.GTC)
            LOGGER.debug("polymarket_order_placed token_id=%s response=%s", token_id, resp)
            return resp
        except Exception as exc:
            err_lower = str(exc).lower()
            # Non-retryable: auth failure, insufficient funds, invalid params
            if any(k in err_lower for k in ("auth", "unauthorized", "insufficient", "invalid")):
                LOGGER.error(
                    "polymarket_order_fatal token_id=%s side=%s error=%s",
                    token_id,
                    side,
                    exc,
                )
                raise
            last_exc = exc
            LOGGER.warning(
                "polymarket_order_error attempt=%d token_id=%s error=%s",
                attempt,
                token_id,
                exc,
            )

    raise RuntimeError(
        f"order placement failed after {config.max_retries + 1} attempts "
        f"token_id={token_id} side={side} last_error={last_exc}"
    )


# ---------------------------------------------------------------------------
# Orderbook-spread execution (YES + NO legs)
# ---------------------------------------------------------------------------

def _execute_orderbook_spread(
    opportunity: Opportunity,
    config: PolymarketConfig,
    ledger: PositionsLedger,
) -> ExecutionResult:
    """Place YES and NO legs for a riskless-spread opportunity.

    If the YES leg fills but the NO leg fails, records an UNHEDGED position
    and logs at CRITICAL level — this must never be silently swallowed.
    """
    total_cost_per_share = opportunity.entry_price_yes + opportunity.entry_price_no
    if total_cost_per_share <= 0:
        return ExecutionResult(
            success=False, error="entry_prices_missing_or_zero"
        )

    # Split size proportionally between legs (each leg gets USDC proportional to its ask)
    n_shares = config.max_trade_usdc / total_cost_per_share
    yes_usdc = n_shares * opportunity.entry_price_yes
    no_usdc = n_shares * opportunity.entry_price_no
    total_usdc = yes_usdc + no_usdc

    # --- YES leg ---
    yes_resp: dict[str, Any] | None = None
    try:
        yes_resp = _place_order(
            config,
            token_id=opportunity.yes_token_id,
            size_usdc=yes_usdc,
            price=opportunity.entry_price_yes,
            side="BUY",
        )
    except Exception as exc:
        return ExecutionResult(
            success=False,
            error=f"yes_leg_failed: {exc}",
        )

    yes_order_id: str = yes_resp.get("orderID", yes_resp.get("order_id", ""))
    yes_fill = float(yes_resp.get("price", opportunity.entry_price_yes))

    # --- NO leg ---
    try:
        no_resp = _place_order(
            config,
            token_id=opportunity.no_token_id,
            size_usdc=no_usdc,
            price=opportunity.entry_price_no,
            side="BUY",
        )
    except Exception as exc:
        # YES filled but NO failed — position is now UNHEDGED
        yes_contracts = yes_usdc / yes_fill if yes_fill > 0 else 0.0
        unhedged = new_position(
            market_condition_id=opportunity.condition_id,
            market_question=opportunity.market_question,
            strategy=opportunity.strategy,
            side="YES",
            entry_price=yes_fill,
            size_usdc=yes_usdc,
            status="unhedged",
            yes_token_id=opportunity.yes_token_id,
            contracts_held=yes_contracts,
        )
        ledger.add(unhedged)
        LOGGER.critical(
            "polymarket_unhedged_position yes_order_id=%s condition_id=%s "
            "yes_usdc=%.2f no_error=%s — manual intervention required",
            yes_order_id,
            opportunity.condition_id,
            yes_usdc,
            exc,
        )
        return ExecutionResult(
            success=False,
            order_id=yes_order_id,
            fill_price=yes_fill,
            size_usdc=yes_usdc,
            error=f"no_leg_failed_unhedged: {exc}",
        )

    no_order_id: str = no_resp.get("orderID", no_resp.get("order_id", ""))
    no_fill = float(no_resp.get("price", opportunity.entry_price_no))
    avg_fill = (yes_fill + no_fill) / 2.0

    position = new_position(
        market_condition_id=opportunity.condition_id,
        market_question=opportunity.market_question,
        strategy=opportunity.strategy,
        side="YES+NO",
        entry_price=avg_fill,
        size_usdc=total_usdc,
        status="open",
        yes_token_id=opportunity.yes_token_id,
        no_token_id=opportunity.no_token_id,
        contracts_held=n_shares,
    )
    ledger.add(position)

    LOGGER.info(
        "polymarket_executed strategy=%s condition_id=%s "
        "yes_order_id=%s no_order_id=%s total_usdc=%.2f avg_fill=%.4f",
        opportunity.strategy,
        opportunity.condition_id,
        yes_order_id,
        no_order_id,
        total_usdc,
        avg_fill,
    )
    return ExecutionResult(
        success=True,
        order_id=f"{yes_order_id}/{no_order_id}",
        fill_price=avg_fill,
        size_usdc=total_usdc,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def execute(
    opportunity: Opportunity,
    config: PolymarketConfig,
    risk_guard: RiskGuard,
    ledger: PositionsLedger,
) -> ExecutionResult:
    """Validate risk checks, then execute the opportunity (or dry-run log it).

    Returns ExecutionResult in all cases — never raises for a failed risk check.
    Only raises for genuinely unrecoverable API errors (invalid auth, etc.).
    """
    proposed_size = config.max_trade_usdc

    # Strategy scope check
    if opportunity.strategy not in _EXECUTABLE_STRATEGIES:
        LOGGER.info(
            "polymarket_execute_skip strategy=%s reason=not_executable_in_phase2",
            opportunity.strategy,
        )
        return ExecutionResult(
            success=False,
            error=f"strategy {opportunity.strategy!r} not executable in Phase 2",
        )

    # Risk checks
    passed, reason = risk_guard.check(opportunity, proposed_size_usdc=proposed_size)
    if not passed:
        LOGGER.info(
            "polymarket_execute_blocked strategy=%s reason=%s",
            opportunity.strategy,
            reason,
        )
        return ExecutionResult(success=False, error=f"risk_check_failed: {reason}")

    # Dry-run mode: log intent and return without touching the API
    if config.dry_run:
        LOGGER.info(
            "polymarket_dry_run strategy=%s edge_pct=%.4f size_usdc=%.2f "
            "action=%s — DRY RUN would have executed",
            opportunity.strategy,
            opportunity.edge_pct,
            proposed_size,
            opportunity.action,
        )
        return ExecutionResult(
            success=True,
            size_usdc=proposed_size,
            error="dry_run",
        )

    # Live execution (strategy-specific routing)
    if opportunity.strategy == "orderbook_spread":
        return _execute_orderbook_spread(opportunity, config, ledger)

    # Should not reach here given the _EXECUTABLE_STRATEGIES check above
    return ExecutionResult(success=False, error="unhandled_strategy")
