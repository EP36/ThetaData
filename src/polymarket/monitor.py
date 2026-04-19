"""Position monitor — polls open positions, detects resolution, manages close lifecycle.

Runs on its own interval (POLY_MONITOR_INTERVAL_SEC) alongside the scan loop.
POLY_DRY_RUN=true (default) logs all intended actions without touching the API.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.polymarket.client import ClobClient
from src.polymarket.config import PolymarketConfig
from src.polymarket.executor import _place_order
from src.polymarket.positions import (
    ACTIVE_STATUSES,
    PositionRecord,
    PositionsLedger,
    _today_date,
)

LOGGER = logging.getLogger("theta.polymarket.monitor")


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------

def _best_bid(orderbook: dict[str, Any]) -> float:
    bids = orderbook.get("bids", [])
    return max((float(b["price"]) for b in bids), default=0.0)


def _fetch_bids(
    client: ClobClient, position: PositionRecord
) -> tuple[float, float]:
    """Return (yes_bid, no_bid). Logs warnings on fetch failure, returns 0.0."""
    yes_bid = no_bid = 0.0

    if position.yes_token_id:
        try:
            yes_bid = _best_bid(client.fetch_orderbook(position.yes_token_id))
        except Exception as exc:
            LOGGER.warning(
                "monitor_bid_fetch_fail token=%s error=%s", position.yes_token_id, exc
            )

    if position.no_token_id:
        try:
            no_bid = _best_bid(client.fetch_orderbook(position.no_token_id))
        except Exception as exc:
            LOGGER.warning(
                "monitor_bid_fetch_fail token=%s error=%s", position.no_token_id, exc
            )

    return yes_bid, no_bid


# ---------------------------------------------------------------------------
# P&L computation
# ---------------------------------------------------------------------------

def compute_unrealized(
    position: PositionRecord, yes_bid: float, no_bid: float
) -> tuple[float, float]:
    """Return (unrealized_pnl, unrealized_pnl_pct) for the position.

    Falls back to estimating contracts_held from entry_price when the field is 0.
    """
    if position.size_usdc <= 0:
        return 0.0, 0.0

    contracts = position.contracts_held

    if position.side == "YES+NO":
        if contracts <= 0 and position.entry_price > 0:
            # entry_price = avg(yes_fill, no_fill) ≈ total_cost / 2_shares
            contracts = position.size_usdc / (2.0 * position.entry_price)
        current_value = contracts * (yes_bid + no_bid)
    elif position.side == "YES":
        if contracts <= 0 and position.entry_price > 0:
            contracts = position.size_usdc / position.entry_price
        current_value = contracts * yes_bid
    elif position.side == "NO":
        if contracts <= 0 and position.entry_price > 0:
            contracts = position.size_usdc / position.entry_price
        current_value = contracts * no_bid
    else:
        return 0.0, 0.0

    unrealized_pnl = current_value - position.size_usdc
    unrealized_pnl_pct = (unrealized_pnl / position.size_usdc) * 100.0
    return unrealized_pnl, unrealized_pnl_pct


# ---------------------------------------------------------------------------
# Close condition checks
# ---------------------------------------------------------------------------

def _seconds_open(position: PositionRecord) -> float:
    try:
        opened = datetime.fromisoformat(position.opened_at)
        return (datetime.now(tz=timezone.utc) - opened).total_seconds()
    except Exception:
        return 0.0


def close_reason(
    position: PositionRecord,
    config: PolymarketConfig,
    unrealized_pnl_pct: float,
) -> str | None:
    """Return a reason string if the position should be closed now, else None.

    Checks in priority order:
      1. Profit target
      2. Stop loss
      3. Time-based exit (max hold hours)
      4. Unhedged grace period expired
    Market resolution is handled separately in _check_resolution().
    """
    # 1 — profit target
    if unrealized_pnl_pct >= config.take_profit_pct:
        return (
            f"profit_target unrealized_pnl_pct={unrealized_pnl_pct:.2f}"
            f" >= {config.take_profit_pct}"
        )

    # 2 — stop loss
    if unrealized_pnl_pct <= -config.stop_loss_pct:
        return (
            f"stop_loss unrealized_pnl_pct={unrealized_pnl_pct:.2f}"
            f" <= -{config.stop_loss_pct}"
        )

    # 3 — max hold time
    hours_open = _seconds_open(position) / 3600.0
    if hours_open >= config.max_hold_hours:
        return (
            f"max_hold_hours hours_open={hours_open:.1f}"
            f" >= {config.max_hold_hours}"
        )

    # 4 — unhedged grace period
    if position.status == "unhedged":
        grace_sec = config.unhedged_grace_minutes * 60.0
        elapsed = _seconds_open(position)
        if elapsed >= grace_sec:
            return (
                f"unhedged_grace_expired elapsed_min={elapsed / 60:.1f}"
                f" >= grace_min={config.unhedged_grace_minutes}"
            )

    return None


# ---------------------------------------------------------------------------
# Market resolution
# ---------------------------------------------------------------------------

def _parse_end_date(raw: str) -> datetime | None:
    """Parse an ISO-8601 end date string, handling missing timezone."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        # Normalise: append Z if no tz designator
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        elif "+" not in raw and raw.count("-") < 3:
            raw += "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _resolution_pnl(position: PositionRecord, winning_outcome: str) -> float:
    """Compute realized P&L after market resolution."""
    wo = winning_outcome.strip().lower()
    contracts = position.contracts_held
    if contracts <= 0 and position.entry_price > 0:
        contracts = position.size_usdc / position.entry_price

    if position.side == "YES+NO":
        # One leg always wins — net payout = contracts * $1.00
        payout = contracts * 1.0
    elif position.side == "YES":
        payout = contracts * (1.0 if wo == "yes" else 0.0)
    elif position.side == "NO":
        payout = contracts * (1.0 if wo == "no" else 0.0)
    else:
        payout = 0.0

    return payout - position.size_usdc


def check_resolution(
    position: PositionRecord,
    market_detail: dict[str, Any],
    ledger: PositionsLedger,
) -> bool:
    """Check if the market resolved or went stale. Returns True if terminal."""
    resolved: bool = bool(market_detail.get("resolved", False))

    if not resolved:
        # Check for stale: end_date passed without resolution
        raw_end = market_detail.get("end_date_iso", position.end_date) or ""
        end_dt = _parse_end_date(raw_end)
        if end_dt and datetime.now(tz=timezone.utc) > end_dt:
            ok = ledger.transition(
                position.id,
                "stale",
                reason=f"end_date_passed end_date={raw_end}",
                end_date=raw_end,
            )
            if ok:
                LOGGER.warning(
                    "polymarket_stale_position id=%s condition_id=%s end_date=%s"
                    " — human intervention required",
                    position.id,
                    position.market_condition_id,
                    raw_end,
                )
        return False  # not yet terminal — still open until stale or resolved

    # Market resolved
    winning_outcome: str = (
        market_detail.get("winning_outcome")
        or market_detail.get("resolved_outcome")
        or ""
    )
    pnl = _resolution_pnl(position, winning_outcome)
    now_iso = datetime.now(tz=timezone.utc).isoformat()

    LOGGER.info(
        "polymarket_market_resolved id=%s condition_id=%s winning_outcome=%s pnl=%.4f",
        position.id,
        position.market_condition_id,
        winning_outcome,
        pnl,
    )

    ledger.transition(
        position.id,
        "resolved",
        reason=f"market_resolved winning_outcome={winning_outcome}",
        pnl=round(pnl, 4),
        closed_at=now_iso,
        exit_price=1.0 if winning_outcome.lower() in ("yes", "no") else 0.0,
    )
    return True


# ---------------------------------------------------------------------------
# Close execution
# ---------------------------------------------------------------------------

def close_position(
    position: PositionRecord,
    config: PolymarketConfig,
    client: ClobClient,
    ledger: PositionsLedger,
) -> bool:
    """Attempt to sell the open token leg(s) of a position.

    Dry-run mode logs "would close" and returns True without API calls.
    On failure: marks "closing" for retry next cycle and logs CRITICAL.
    On success: marks "closed" with realized P&L.
    """
    if config.dry_run:
        LOGGER.info(
            "polymarket_dry_run_close id=%s side=%s status=%s size_usdc=%.2f"
            " — DRY RUN would have closed",
            position.id,
            position.side,
            position.status,
            position.size_usdc,
        )
        return True

    # Mark as "closing" before touching the API (allows retry on crash)
    if position.status != "closing":
        ledger.transition(position.id, "closing", reason="close_initiated")

    # Determine which tokens to sell and at what price
    tokens_to_sell: list[tuple[str, float]] = []  # (token_id, best_bid)
    try:
        if position.side in ("YES", "YES+NO") and position.yes_token_id:
            yes_bid = _best_bid(client.fetch_orderbook(position.yes_token_id))
            tokens_to_sell.append((position.yes_token_id, yes_bid))
        if position.side in ("NO", "YES+NO") and position.no_token_id:
            no_bid = _best_bid(client.fetch_orderbook(position.no_token_id))
            tokens_to_sell.append((position.no_token_id, no_bid))
    except Exception as exc:
        LOGGER.critical(
            "polymarket_close_orderbook_fail id=%s error=%s"
            " — position stays in closing for retry",
            position.id,
            exc,
        )
        return False

    if not tokens_to_sell:
        LOGGER.error(
            "polymarket_close_no_tokens id=%s side=%s"
            " — no token_ids on record, cannot close",
            position.id,
            position.side,
        )
        return False

    contracts = position.contracts_held
    if contracts <= 0 and position.entry_price > 0:
        contracts = position.size_usdc / position.entry_price
    contracts_per_leg = contracts / max(len(tokens_to_sell), 1)

    total_exit_value = 0.0
    all_filled = True

    for token_id, bid in tokens_to_sell:
        # Aggressive limit: 1 cent below best bid to get to front of queue
        sell_price = max(bid - 0.01, 0.01)
        sell_usdc = contracts_per_leg * sell_price
        try:
            resp = _place_order(config, token_id, sell_usdc, sell_price, "SELL")
            fill_price = float(resp.get("price", sell_price))
            total_exit_value += contracts_per_leg * fill_price
            LOGGER.debug(
                "monitor_close_leg_filled token_id=%s fill=%.4f", token_id, fill_price
            )
        except Exception as exc:
            LOGGER.critical(
                "polymarket_close_leg_failed id=%s token_id=%s error=%s"
                " — position remains in closing for retry",
                position.id,
                token_id,
                exc,
            )
            all_filled = False

    if not all_filled:
        return False

    avg_exit = total_exit_value / max(contracts, 1e-9)
    realized_pnl = total_exit_value - position.size_usdc
    now_iso = datetime.now(tz=timezone.utc).isoformat()

    ledger.transition(
        position.id,
        "closed",
        reason="close_filled",
        pnl=round(realized_pnl, 4),
        exit_price=round(avg_exit, 6),
        closed_at=now_iso,
    )
    LOGGER.info(
        "polymarket_position_closed id=%s pnl=%.4f exit_price=%.4f",
        position.id,
        realized_pnl,
        avg_exit,
    )
    return True


# ---------------------------------------------------------------------------
# Per-position monitor cycle
# ---------------------------------------------------------------------------

def _monitor_one(
    position: PositionRecord,
    config: PolymarketConfig,
    client: ClobClient,
    ledger: PositionsLedger,
) -> None:
    """Run one monitor cycle for a single position."""

    # Positions in "closing" state: just retry the close
    if position.status == "closing":
        LOGGER.info("polymarket_monitor_retry_close id=%s", position.id)
        close_position(position, config, client, ledger)
        return

    # Fetch current prices
    yes_bid, no_bid = _fetch_bids(client, position)

    # Compute and persist latest unrealized P&L
    unrealized_pnl, unrealized_pnl_pct = compute_unrealized(position, yes_bid, no_bid)
    ledger.update_fields(
        position.id,
        unrealized_pnl=round(unrealized_pnl, 4),
        unrealized_pnl_pct=round(unrealized_pnl_pct, 4),
    )

    LOGGER.info(
        "polymarket_monitor_tick id=%s side=%s entry=%.4f yes_bid=%.4f no_bid=%.4f"
        " unrealized_pnl=%.4f unrealized_pnl_pct=%.2f",
        position.id,
        position.side,
        position.entry_price,
        yes_bid,
        no_bid,
        unrealized_pnl,
        unrealized_pnl_pct,
    )

    # Check market resolution (stale / resolved terminal states)
    try:
        market_detail = client.fetch_market_detail(position.market_condition_id)
        if check_resolution(position, market_detail, ledger):
            return
    except Exception as exc:
        LOGGER.warning(
            "polymarket_monitor_resolution_fail id=%s error=%s", position.id, exc
        )

    # Check close conditions
    reason = close_reason(position, config, unrealized_pnl_pct)
    if reason:
        LOGGER.info(
            "polymarket_monitor_trigger_close id=%s reason=%s", position.id, reason
        )
        close_position(position, config, client, ledger)


# ---------------------------------------------------------------------------
# Daily P&L summary
# ---------------------------------------------------------------------------

def emit_daily_summary(
    all_positions: list[PositionRecord],
    config: PolymarketConfig,
    ledger: PositionsLedger,
) -> dict[str, Any]:
    """Compute and log the daily P&L rollup. Returns the summary dict.

    Writes a JSON line to logs/poly_YYYY-MM-DD.log in addition to stdout.
    Emits a WARNING if within 20% of the daily loss limit.
    """
    active = [p for p in all_positions if p.status in ACTIVE_STATUSES]
    total_deployed = sum(p.size_usdc for p in active)
    total_unrealized = sum((p.unrealized_pnl or 0.0) for p in active)
    realized_today = ledger.daily_pnl()
    combined = realized_today + total_unrealized

    within_warning = realized_today < -(config.daily_loss_limit * 0.80)
    if within_warning:
        LOGGER.warning(
            "polymarket_loss_limit_warning realized_pnl=%.2f limit=%.2f"
            " — within 20%% of daily loss limit",
            realized_today,
            config.daily_loss_limit,
        )

    LOGGER.info(
        "polymarket_daily_summary open=%d deployed=%.2f unrealized=%.4f"
        " realized=%.4f combined=%.4f loss_warn=%s",
        len(active),
        total_deployed,
        total_unrealized,
        realized_today,
        combined,
        within_warning,
    )

    summary: dict[str, Any] = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "open_count": len(active),
        "usdc_deployed": round(total_deployed, 2),
        "unrealized_pnl": round(total_unrealized, 4),
        "realized_pnl_today": round(realized_today, 4),
        "combined_daily_pnl": round(combined, 4),
        "daily_loss_limit": config.daily_loss_limit,
        "within_20pct_of_limit": within_warning,
    }

    log_path = Path(config.poly_log_dir) / f"poly_{_today_date()}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary) + "\n")
    except OSError as exc:
        LOGGER.error("monitor_daily_log_fail path=%s error=%s", log_path, exc)

    return summary


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def monitor_positions(
    config: PolymarketConfig,
    client: ClobClient,
    ledger: PositionsLedger,
) -> None:
    """Check all active positions, act on close conditions, emit daily summary.

    Safe to call on any cadence — idempotent except for writes triggered by
    close conditions or resolved markets.
    """
    positions = ledger.load()
    active = [p for p in positions if p.status in ACTIVE_STATUSES]

    LOGGER.info(
        "polymarket_monitor_start active=%d total=%d",
        len(active),
        len(positions),
    )

    for position in active:
        try:
            _monitor_one(position, config, client, ledger)
        except Exception as exc:
            LOGGER.error(
                "polymarket_monitor_position_error id=%s error=%s", position.id, exc
            )

    # Reload after potential status updates
    positions = ledger.load()
    emit_daily_summary(positions, config, ledger)
