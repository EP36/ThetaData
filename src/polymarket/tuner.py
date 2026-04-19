"""Parameter tuner — analyzes closed trade outcomes and proposes updates to
signal_params.json. Human approval required before changes are applied.

Public API:
  ParamChange     — one proposed parameter change
  TuningResult    — full tuning proposal
  RULE_NOTE_TO_PARAM — maps signal_note prefix -> param name
  check_minimum_data(records, days) -> (ok: bool, reason: str)
  propose_tuning(records, days, params_path) -> TuningResult
  write_proposal(result, proposal_path) -> None
  read_proposal(proposal_path) -> dict | None
  apply_proposal(proposal_path, params_path, history_dir) -> dict[str, str]
  reject_proposal(proposal_path) -> None
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from src.polymarket.feedback import FeedbackRecord

LOGGER = logging.getLogger("theta.polymarket.tuner")

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Rule → param mapping
# ---------------------------------------------------------------------------

RULE_NOTE_TO_PARAM: dict[str, str] = {
    "direction_aligned_bullish": "direction_bullish_up_multiplier",
    "direction_opposed_bullish": "direction_bullish_down_multiplier",
    "direction_aligned_bearish": "direction_bearish_down_multiplier",
    "direction_opposed_bearish": "direction_bearish_up_multiplier",
    "rsi_overbought": "rsi_overbought_multiplier",
    "rsi_oversold": "rsi_oversold_multiplier",
    "macd_bullish_crossover": "macd_crossover_bonus",
    "green_streak": "streak_bonus",
    "volume_spike": "volume_spike_bonus",
    "volume_low": "volume_low_multiplier",
    "threshold_proximity": "proximity_close_multiplier",
    "threshold_clearance": "proximity_far_bonus",
    "high_volatility": "volatility_high_multiplier",
    "high_atr": "atr_high_multiplier",
}

# ---------------------------------------------------------------------------
# Param bounds / classification
# ---------------------------------------------------------------------------

_MULTIPLIER_PARAMS: set[str] = {
    "direction_bullish_up_multiplier",
    "direction_bullish_down_multiplier",
    "direction_bearish_down_multiplier",
    "direction_bearish_up_multiplier",
    "rsi_overbought_multiplier",
    "rsi_oversold_multiplier",
    "volume_low_multiplier",
    "proximity_close_multiplier",
    "volatility_high_multiplier",
    "atr_high_multiplier",
}

_BONUS_PARAMS: set[str] = {
    "macd_crossover_bonus",
    "streak_bonus",
    "volume_spike_bonus",
    "proximity_far_bonus",
}

_MULTIPLIER_BOUNDS = (0.50, 1.50)
_BONUS_BOUNDS = (0.00, 0.15)
_MAX_CHANGE_FRACTION = 0.20   # max 20% change per run
_MIN_TRADES_PER_RULE = 10
_EFFECTIVENESS_THRESHOLD = 0.05


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ParamChange:
    """One proposed parameter change."""
    param: str
    current_value: float
    proposed_value: float
    effectiveness: float
    applied_count: int
    direction: str  # "increase" | "decrease"


@dataclass
class TuningResult:
    """Full tuning proposal."""
    generated_at: str
    days_analyzed: int
    trade_count: int
    overall_win_rate: float
    avg_pnl_pct: float
    proposed_changes: list[ParamChange] = field(default_factory=list)
    unchanged_params: list[str] = field(default_factory=list)
    insufficient_data_params: list[str] = field(default_factory=list)
    strategy_breakdown: dict[str, dict] = field(default_factory=dict)
    proposed_params: dict[str, float] = field(default_factory=dict)
    data_ok: bool = True
    skip_reason: str = ""


# ---------------------------------------------------------------------------
# check_minimum_data
# ---------------------------------------------------------------------------

def check_minimum_data(
    records: list[FeedbackRecord],
    days: int = 30,
) -> tuple[bool, str]:
    """Return (ok, reason). ok=False means tuning should be skipped."""
    if not records:
        return False, "no closed trades found"

    n = len(records)
    if n < 20:
        return False, f"only {n} closed trades in last {days} days (minimum 20 required)"

    # Count unique calendar days from opened_at
    dates: set[str] = set()
    for r in records:
        try:
            dt = datetime.fromisoformat(r.opened_at)
            dates.add(dt.strftime("%Y-%m-%d"))
        except (ValueError, TypeError):
            pass

    if len(dates) < 10:
        return False, (
            f"only {len(dates)} calendar days of data (minimum 10 required)"
        )

    return True, ""


# ---------------------------------------------------------------------------
# Rule effectiveness
# ---------------------------------------------------------------------------

def _compute_rule_effectiveness(
    records: list[FeedbackRecord],
    rule_note_prefix: str,
) -> tuple[float, int]:
    """Return (effectiveness, applied_count).

    effectiveness = applied_win_rate - baseline_win_rate
    """
    applied = [r for r in records if rule_note_prefix in r.rules_applied]
    baseline = [r for r in records if rule_note_prefix not in r.rules_applied]

    if not applied:
        return 0.0, 0
    if not baseline:
        return 0.0, len(applied)

    applied_win_rate = sum(1 for r in applied if r.outcome == "win") / len(applied)
    baseline_win_rate = sum(1 for r in baseline if r.outcome == "win") / len(baseline)
    effectiveness = applied_win_rate - baseline_win_rate

    return effectiveness, len(applied)


# ---------------------------------------------------------------------------
# propose_tuning
# ---------------------------------------------------------------------------

def propose_tuning(
    records: list[FeedbackRecord],
    days: int = 30,
    params_path: str | None = None,
) -> TuningResult:
    """Analyze records and propose parameter adjustments."""
    now_iso = datetime.now(UTC).isoformat()

    ok, reason = check_minimum_data(records, days)
    if not ok:
        return TuningResult(
            generated_at=now_iso,
            days_analyzed=days,
            trade_count=len(records),
            overall_win_rate=0.0,
            avg_pnl_pct=0.0,
            data_ok=False,
            skip_reason=reason,
        )

    # Load current params
    from src.polymarket.signals import load_signal_params, _PARAMS
    if params_path:
        current_params = load_signal_params(params_path)
    else:
        current_params = dict(_PARAMS)

    # Overall stats
    wins = sum(1 for r in records if r.outcome == "win")
    overall_win_rate = wins / len(records)
    avg_pnl_pct = sum(r.realized_pnl_pct for r in records) / len(records)

    # Strategy breakdown
    strategy_breakdown: dict[str, dict] = {}
    strat_buckets: dict[str, list[FeedbackRecord]] = {}
    for r in records:
        strat_buckets.setdefault(r.strategy, []).append(r)
    for strat, recs in strat_buckets.items():
        s_wins = sum(1 for r in recs if r.outcome == "win")
        strategy_breakdown[strat] = {
            "count": len(recs),
            "win_rate": round(s_wins / len(recs), 4) if recs else 0.0,
            "avg_pnl": round(
                sum(r.realized_pnl_pct for r in recs) / len(recs), 4
            ) if recs else 0.0,
        }

    proposed_changes: list[ParamChange] = []
    unchanged_params: list[str] = []
    insufficient_data_params: list[str] = []

    for rule_note_prefix, param_name in RULE_NOTE_TO_PARAM.items():
        effectiveness, applied_count = _compute_rule_effectiveness(
            records, rule_note_prefix
        )

        if applied_count < _MIN_TRADES_PER_RULE:
            insufficient_data_params.append(param_name)
            continue

        if abs(effectiveness) <= _EFFECTIVENESS_THRESHOLD:
            unchanged_params.append(param_name)
            continue

        current_val = current_params.get(param_name, 1.0)

        # Compute proposed value
        if effectiveness > _EFFECTIVENESS_THRESHOLD:
            # Rule is helping — strengthen it
            new_val = current_val * 1.10
            change_dir = "increase"
        else:
            # Rule is hurting — weaken it
            new_val = current_val * 0.90
            change_dir = "decrease"

        # Clamp to max 20% change per run
        max_change = current_val * _MAX_CHANGE_FRACTION
        actual_change = new_val - current_val
        if abs(actual_change) > max_change:
            new_val = current_val + (max_change if actual_change > 0 else -max_change)

        # Apply bounds
        if param_name in _MULTIPLIER_PARAMS:
            lo, hi = _MULTIPLIER_BOUNDS
        elif param_name in _BONUS_PARAMS:
            lo, hi = _BONUS_BOUNDS
        else:
            lo, hi = _MULTIPLIER_BOUNDS

        new_val = max(lo, min(hi, new_val))
        new_val = round(new_val, 6)

        if new_val == round(current_val, 6):
            unchanged_params.append(param_name)
            continue

        proposed_changes.append(
            ParamChange(
                param=param_name,
                current_value=current_val,
                proposed_value=new_val,
                effectiveness=round(effectiveness, 4),
                applied_count=applied_count,
                direction=change_dir,
            )
        )

    # Build the full proposed params dict (current + changes applied)
    proposed_params = dict(current_params)
    for change in proposed_changes:
        proposed_params[change.param] = change.proposed_value

    return TuningResult(
        generated_at=now_iso,
        days_analyzed=days,
        trade_count=len(records),
        overall_win_rate=round(overall_win_rate, 4),
        avg_pnl_pct=round(avg_pnl_pct, 4),
        proposed_changes=proposed_changes,
        unchanged_params=unchanged_params,
        insufficient_data_params=insufficient_data_params,
        strategy_breakdown=strategy_breakdown,
        proposed_params=proposed_params,
        data_ok=True,
        skip_reason="",
    )


# ---------------------------------------------------------------------------
# write_proposal / read_proposal
# ---------------------------------------------------------------------------

def write_proposal(result: TuningResult, proposal_path: str) -> None:
    """Serialize tuning result to JSON and write to proposal_path."""
    path = Path(proposal_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Convert ParamChange list to dicts for JSON
    changes_dicts = []
    for c in result.proposed_changes:
        changes_dicts.append({
            "param": c.param,
            "current_value": c.current_value,
            "proposed_value": c.proposed_value,
            "effectiveness": c.effectiveness,
            "applied_count": c.applied_count,
            "direction": c.direction,
        })

    payload = {
        "generated_at": result.generated_at,
        "days_analyzed": result.days_analyzed,
        "trade_count": result.trade_count,
        "overall_win_rate": result.overall_win_rate,
        "avg_pnl_pct": result.avg_pnl_pct,
        "proposed_changes": changes_dicts,
        "unchanged_params": result.unchanged_params,
        "insufficient_data_params": result.insufficient_data_params,
        "strategy_breakdown": result.strategy_breakdown,
        "proposed_params": result.proposed_params,
        "data_ok": result.data_ok,
        "skip_reason": result.skip_reason,
    }

    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    LOGGER.info(
        "tuner_proposal_written path=%s changes=%d",
        path,
        len(result.proposed_changes),
    )


def read_proposal(proposal_path: str) -> dict | None:
    """Read proposal JSON, return dict or None if missing."""
    path = Path(proposal_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("tuner_proposal_read_failed path=%s error=%s", path, exc)
        return None


# ---------------------------------------------------------------------------
# apply_proposal
# ---------------------------------------------------------------------------

def apply_proposal(
    proposal_path: str,
    params_path: str,
    history_dir: str,
) -> dict[str, str]:
    """Apply the pending proposal to params_path and return a change log dict."""
    proposal = read_proposal(proposal_path)
    if proposal is None:
        raise FileNotFoundError(f"No proposal found at {proposal_path}")

    params_file = Path(params_path)
    history = Path(history_dir)
    history.mkdir(parents=True, exist_ok=True)

    # Count existing backups to determine version number
    existing = sorted(history.glob("signal_params_v*.json"))
    next_version = len(existing) + 1

    # Back up current params
    if params_file.exists():
        backup_path = history / f"signal_params_v{next_version}.json"
        shutil.copy2(params_file, backup_path)
        LOGGER.info("tuner_params_backed_up backup=%s", backup_path)

    # Build new params file content
    # Load current file structure to preserve metadata fields
    current_file: dict = {}
    if params_file.exists():
        try:
            current_file = json.loads(params_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    proposed_params: dict[str, float] = proposal.get("proposed_params", {})
    now_iso = datetime.now(UTC).isoformat()

    new_content = dict(current_file)
    new_content["version"] = current_file.get("version", 1)
    new_content["updated_at"] = now_iso
    new_content["updated_by"] = "tuner"
    new_content["params"] = proposed_params

    # Update performance block
    perf = dict(current_file.get("performance", {}))
    perf["total_trades"] = proposal.get("trade_count", perf.get("total_trades", 0))
    perf["win_rate"] = proposal.get("overall_win_rate")
    perf["avg_pnl_pct"] = proposal.get("avg_pnl_pct")
    perf["last_evaluated_at"] = proposal.get("generated_at")
    new_content["performance"] = perf

    params_file.parent.mkdir(parents=True, exist_ok=True)
    params_file.write_text(json.dumps(new_content, indent=2), encoding="utf-8")

    # Reload in-process params
    from src.polymarket.signals import reload_signal_params
    reload_signal_params()

    # Build change log
    change_log: dict[str, str] = {}
    for c in proposal.get("proposed_changes", []):
        param = c.get("param", "")
        old_val = c.get("current_value", "?")
        new_val = c.get("proposed_value", "?")
        eff = c.get("effectiveness", 0.0)
        change_log[param] = (
            f"{old_val} -> {new_val} (effectiveness: {eff:+.4f})"
        )
        LOGGER.info(
            "tuner_param_changed param=%s old=%s new=%s effectiveness=%+.4f",
            param,
            old_val,
            new_val,
            eff,
        )

    # Clean up proposal file
    try:
        Path(proposal_path).unlink()
    except OSError:
        pass

    LOGGER.info("tuner_apply_complete changes=%d", len(change_log))
    return change_log


# ---------------------------------------------------------------------------
# reject_proposal
# ---------------------------------------------------------------------------

def reject_proposal(proposal_path: str) -> None:
    """Delete the proposal file (missing_ok). Log rejection."""
    path = Path(proposal_path)
    try:
        path.unlink()
        LOGGER.info("tuner_proposal_rejected path=%s", path)
    except FileNotFoundError:
        LOGGER.info("tuner_proposal_reject_noop path=%s (already missing)", path)
    except OSError as exc:
        LOGGER.warning("tuner_proposal_reject_failed path=%s error=%s", path, exc)
