"""Safety validator — hard limits the AI cannot override.

SafetyValidator.validate() returns None if any check fails.
All failure paths log the specific check that failed with the violating value.
"""

from __future__ import annotations

import logging
from typing import Any

from trauto.ai.analyst import AIAnalysis

LOGGER = logging.getLogger("trauto.ai.validator")

_MULTIPLIER_BOUNDS = (0.50, 1.50)
_BONUS_BOUNDS = (0.00, 0.15)
_MAX_PARAMS_CHANGED = 3
_MAX_CHANGE_FRACTION = 0.20
_MIN_WIN_RATE = 0.30
_MIN_TRADE_COUNT = 20
_MIN_CONFIDENCE = 0.60

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

# These are env-var-controlled settings that must never appear in proposed_params
_PROTECTED_ENV_PARAMS: set[str] = {
    "poly_dry_run",
    "global_daily_loss_limit",
    "global_max_positions",
    "dry_run",
    "max_positions",
    "daily_loss_limit",
}


class SafetyValidator:
    """Validates AIAnalysis proposals against hard safety limits."""

    def validate(
        self,
        analysis: AIAnalysis,
        current_params: dict[str, float],
    ) -> AIAnalysis | None:
        """Return the analysis unchanged if it passes all checks, else None."""

        # Gate 1: sufficient data basis
        if analysis.trade_count_analyzed < _MIN_TRADE_COUNT:
            LOGGER.warning(
                "safety_reject reason=insufficient_trades "
                "trade_count=%d min=%d",
                analysis.trade_count_analyzed,
                _MIN_TRADE_COUNT,
            )
            return None

        if analysis.win_rate < _MIN_WIN_RATE:
            LOGGER.warning(
                "safety_reject reason=win_rate_too_low "
                "win_rate=%.3f min=%.3f",
                analysis.win_rate,
                _MIN_WIN_RATE,
            )
            return None

        if analysis.confidence < _MIN_CONFIDENCE:
            LOGGER.warning(
                "safety_reject reason=confidence_too_low "
                "confidence=%.3f min=%.3f",
                analysis.confidence,
                _MIN_CONFIDENCE,
            )
            return None

        # Gate 2: count changed params
        changed = _find_changed_params(analysis.proposed_params, current_params)

        if len(changed) > _MAX_PARAMS_CHANGED:
            LOGGER.warning(
                "safety_reject reason=too_many_params_changed "
                "changed=%d max=%d params=%s",
                len(changed),
                _MAX_PARAMS_CHANGED,
                list(changed),
            )
            return None

        # Gate 3: per-param bound and magnitude checks
        for param, new_val in analysis.proposed_params.items():
            # Protected env params must not appear
            if param.lower() in _PROTECTED_ENV_PARAMS:
                LOGGER.warning(
                    "safety_reject reason=protected_param_modified param=%s", param
                )
                return None

            # Only known signal params are allowed
            if param not in _MULTIPLIER_PARAMS and param not in _BONUS_PARAMS:
                LOGGER.warning(
                    "safety_reject reason=unknown_param param=%s value=%s", param, new_val
                )
                return None

            # Bounds check
            if param in _MULTIPLIER_PARAMS:
                lo, hi = _MULTIPLIER_BOUNDS
            else:
                lo, hi = _BONUS_BOUNDS

            if not (lo <= new_val <= hi):
                LOGGER.warning(
                    "safety_reject reason=param_out_of_bounds "
                    "param=%s value=%.4f bounds=[%.2f, %.2f]",
                    param, new_val, lo, hi,
                )
                return None

            # Max change magnitude check
            old_val = current_params.get(param, new_val)
            if old_val != 0:
                change_frac = abs(new_val - old_val) / abs(old_val)
                if change_frac > _MAX_CHANGE_FRACTION:
                    LOGGER.warning(
                        "safety_reject reason=param_change_too_large "
                        "param=%s old=%.4f new=%.4f change_pct=%.1f max_pct=%.0f",
                        param, old_val, new_val,
                        change_frac * 100, _MAX_CHANGE_FRACTION * 100,
                    )
                    return None

        LOGGER.info(
            "safety_passed confidence=%.2f trade_count=%d changed_params=%d",
            analysis.confidence,
            analysis.trade_count_analyzed,
            len(changed),
        )
        return analysis


def _find_changed_params(
    proposed: dict[str, float],
    current: dict[str, float],
) -> set[str]:
    """Return set of param names that differ between proposed and current."""
    changed: set[str] = set()
    for k, new_val in proposed.items():
        old_val = current.get(k)
        if old_val is None:
            changed.add(k)
        elif abs(new_val - old_val) > 1e-9:
            changed.add(k)
    return changed


def compute_change_impact(
    proposed: dict[str, float],
    current: dict[str, float],
) -> float:
    """Return average absolute change fraction across all changed params (0-1)."""
    changes = []
    for k, new_val in proposed.items():
        old_val = current.get(k, new_val)
        if old_val != 0:
            changes.append(abs(new_val - old_val) / abs(old_val))
    return sum(changes) / len(changes) if changes else 0.0
