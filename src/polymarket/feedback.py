"""Feedback data pipeline — reads realized P&L from Phase 3 logs and positions
ledger and produces FeedbackRecord objects for the parameter tuner.

The key approximation: BTC signal state at trade open time is reconstructed
from the closest daily log entry (emit_daily_summary) on the opened_at date.
Positions opened before BTC signal logging was added have empty signals.

Public API:
  FeedbackRecord         — dataclass for one closed trade outcome
  load_feedback_records(days, positions_path, log_dir) -> list[FeedbackRecord]
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from src.polymarket.opportunities import Opportunity
from src.polymarket.positions import PositionRecord
from src.polymarket.signals import classify_direction, score_opportunity

if TYPE_CHECKING:
    from src.polymarket.alpaca_signals import BtcSignals

LOGGER = logging.getLogger("theta.polymarket.feedback")

UTC = timezone.utc


# ---------------------------------------------------------------------------
# FeedbackRecord
# ---------------------------------------------------------------------------

@dataclass
class FeedbackRecord:
    """One closed trade outcome used for parameter tuning."""

    trade_id: str
    opened_at: str
    closed_at: str
    strategy: str
    direction: str           # from classify_direction()
    realized_pnl_pct: float  # pos.pnl / pos.size_usdc * 100
    outcome: str             # "win" | "loss"
    signals_at_open: dict    # btc_signals dict from daily log snapshot
    rules_applied: list[str] # first-word prefixes from signal_notes
    base_confidence: float   # 0.50 default (not stored in ledger)
    adjusted_confidence: float  # from replayed score_opportunity()
    edge_pct: float          # 0.0 (not stored in ledger)


# ---------------------------------------------------------------------------
# Log reading helpers
# ---------------------------------------------------------------------------

def _read_daily_logs(log_dir: str, days: int) -> dict[str, list[dict]]:
    """Return {date_str: [log_entry, ...]} for log files in the last N days."""
    result: dict[str, list[dict]] = {}
    log_path = Path(log_dir)

    if not log_path.exists():
        LOGGER.warning("feedback_log_dir_missing path=%s", log_path)
        return result

    cutoff_date = (datetime.now(UTC) - timedelta(days=days)).date()

    for fpath in log_path.glob("poly_*.log"):
        # Extract date from filename: poly_YYYY-MM-DD.log
        stem = fpath.stem  # e.g. "poly_2024-01-01"
        try:
            date_str = stem[5:]  # strip "poly_"
            file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, IndexError):
            LOGGER.debug("feedback_skip_log_file path=%s", fpath)
            continue

        if file_date < cutoff_date:
            continue

        entries: list[dict] = []
        try:
            text = fpath.read_text(encoding="utf-8")
        except OSError as exc:
            LOGGER.warning("feedback_log_read_failed path=%s error=%s", fpath, exc)
            continue

        for lineno, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and obj:
                    entries.append(obj)
            except json.JSONDecodeError:
                LOGGER.debug(
                    "feedback_malformed_log_line path=%s line=%d", fpath, lineno
                )
                continue

        if entries:
            result[date_str] = entries

    return result


def _find_closest_entry(entries: list[dict], target_iso: str) -> dict | None:
    """Return the log entry whose 'ts' is closest to target_iso."""
    if not entries:
        return None

    try:
        target_dt = datetime.fromisoformat(target_iso)
        if target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return entries[0]

    best: dict | None = None
    best_delta = float("inf")

    for entry in entries:
        ts_str = entry.get("ts")
        if not ts_str:
            continue
        try:
            entry_dt = datetime.fromisoformat(ts_str)
            if entry_dt.tzinfo is None:
                entry_dt = entry_dt.replace(tzinfo=UTC)
            delta = abs((entry_dt - target_dt).total_seconds())
            if delta < best_delta:
                best_delta = delta
                best = entry
        except (ValueError, TypeError):
            continue

    return best or (entries[0] if entries else None)


def _pos_to_opportunity(pos: PositionRecord) -> Opportunity:
    """Reconstruct an Opportunity from a PositionRecord (approximate)."""
    return Opportunity(
        strategy=pos.strategy,
        market_question=pos.market_question,
        edge_pct=2.0,  # unknown, use representative default
        action=f"buy YES @ {pos.entry_price:.4f}",
        confidence="medium",
        notes="",
    )


def _signals_from_log(entry: dict) -> "BtcSignals | None":
    """Return BtcSignals if btc_signals present and data_available, else None."""
    from src.polymarket.alpaca_signals import BtcSignals

    btc = entry.get("btc_signals")
    if not isinstance(btc, dict):
        return None
    if not btc.get("data_available"):
        return None

    try:
        return BtcSignals(
            data_available=True,
            price_usd=float(btc.get("price_usd", 0.0)),
            change_24h_pct=float(btc.get("change_24h_pct", 0.0)),
            rsi_14=float(btc.get("rsi_14", 50.0)),
            macd_crossover=str(btc.get("macd_crossover", "none")),
            consecutive_bars=int(btc.get("consecutive_bars", 0)),
            streak_direction=str(btc.get("streak_direction", "none")),
            volume_ratio=float(btc.get("volume_ratio", 1.0)),
            bb_width_ratio=float(btc.get("bb_width_ratio", 1.0)),
            atr_ratio=float(btc.get("atr_ratio", 1.0)),
        )
    except (TypeError, ValueError) as exc:
        LOGGER.debug("feedback_signals_parse_failed error=%s", exc)
        return None


def _unavailable_signals() -> "BtcSignals":
    """Return a BtcSignals with data_available=False."""
    from src.polymarket.alpaca_signals import BtcSignals
    return BtcSignals(data_available=False)


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def load_feedback_records(
    days: int = 30,
    positions_path: str = "data/polymarket_positions.json",
    log_dir: str = "logs",
) -> list[FeedbackRecord]:
    """Return FeedbackRecord for all closed/resolved trades in the last N days."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Load positions
    pos_path = Path(positions_path)
    if not pos_path.exists():
        LOGGER.info("feedback_no_positions_file path=%s", pos_path)
        return []

    try:
        raw_positions = json.loads(pos_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("feedback_positions_load_failed path=%s error=%s", pos_path, exc)
        return []

    if not isinstance(raw_positions, list):
        LOGGER.warning("feedback_positions_not_list path=%s", pos_path)
        return []

    # Parse into PositionRecord objects
    positions: list[PositionRecord] = []
    for raw in raw_positions:
        if not isinstance(raw, dict):
            continue
        try:
            pos = PositionRecord(**{
                k: v for k, v in raw.items()
                if k in PositionRecord.__dataclass_fields__
            })
            positions.append(pos)
        except (TypeError, ValueError) as exc:
            LOGGER.debug("feedback_position_parse_failed error=%s", exc)
            continue

    # Filter to closed/resolved in last N days
    terminal_positions: list[PositionRecord] = []
    for pos in positions:
        if pos.status not in {"closed", "resolved"}:
            continue
        # Use closed_at, fall back to opened_at
        date_str = pos.closed_at or pos.opened_at
        if not date_str:
            continue
        try:
            dt = datetime.fromisoformat(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            if dt >= cutoff:
                terminal_positions.append(pos)
        except (ValueError, TypeError):
            continue

    if not terminal_positions:
        LOGGER.info("feedback_no_terminal_positions days=%d", days)
        return []

    # Read daily logs
    daily_logs = _read_daily_logs(log_dir, days)

    records: list[FeedbackRecord] = []

    for pos in terminal_positions:
        # Determine opened_at date
        try:
            opened_dt = datetime.fromisoformat(pos.opened_at)
            if opened_dt.tzinfo is None:
                opened_dt = opened_dt.replace(tzinfo=UTC)
            open_date_str = opened_dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            open_date_str = ""

        # Find log entries for opened_at date
        log_entries = daily_logs.get(open_date_str, [])
        closest = _find_closest_entry(log_entries, pos.opened_at)

        # Extract btc_signals
        signals_dict: dict = {}
        btc_signals = None
        if closest:
            raw_btc = closest.get("btc_signals", {})
            if isinstance(raw_btc, dict):
                signals_dict = raw_btc
            btc_signals = _signals_from_log(closest)

        if btc_signals is None:
            btc_signals = _unavailable_signals()

        # Build fake Opportunity for scoring
        opp = _pos_to_opportunity(pos)
        direction = classify_direction(opp)

        # Replay scoring to get rules_applied
        scored = score_opportunity(opp, btc_signals)
        signal_notes = list(scored.signal_notes) if scored.signal_notes else []

        rules_applied = [
            n.split()[0]
            for n in signal_notes
            if n != "no_signal_rules_triggered"
        ]

        # Compute P&L
        size = pos.size_usdc or 1.0
        pnl = pos.pnl if pos.pnl is not None else 0.0
        realized_pnl_pct = (pnl / size) * 100.0
        outcome = "win" if pnl >= 0 else "loss"

        # Adjusted confidence from scored opportunity
        adjusted_confidence = (
            scored.confidence_score
            if scored.confidence_score > 0
            else 0.50
        )

        record = FeedbackRecord(
            trade_id=pos.id,
            opened_at=pos.opened_at,
            closed_at=pos.closed_at or pos.opened_at,
            strategy=pos.strategy,
            direction=direction,
            realized_pnl_pct=round(realized_pnl_pct, 4),
            outcome=outcome,
            signals_at_open=signals_dict,
            rules_applied=rules_applied,
            base_confidence=0.50,
            adjusted_confidence=round(adjusted_confidence, 4),
            edge_pct=0.0,
        )
        records.append(record)

    LOGGER.info(
        "feedback_records_loaded count=%d days=%d", len(records), days
    )
    return records
