"""Signal engine — classifies opportunity direction and adjusts confidence scores.

score_opportunity() is the primary entry point.  It converts the string
confidence from Phase 1 to a float, applies a chain of BTC-market-signal
rules, then returns a new (frozen) Opportunity with updated confidence_score,
rank_score, direction, and signal_notes fields.

Confidence is always clamped to [0.05, 0.95].  If signals are unavailable
(btc_signals.data_available is False) the original opportunity is returned
unchanged.  If scoring itself raises, the original is returned with a
warning logged — signals never block execution.

Signal parameters are loaded from a JSON file (POLY_SIGNAL_PARAMS_PATH env var,
default polymarket/signal_params.json) at module level and can be reloaded
at runtime via reload_signal_params().
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.polymarket.alpaca_signals import BtcSignals

from src.polymarket.opportunities import Opportunity, _extract_usd_threshold

LOGGER = logging.getLogger("theta.polymarket.signals")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CONFIDENCE_MAP: dict[str, float] = {
    "high": 0.80,
    "medium": 0.50,
    "low": 0.25,
}
_CONFIDENCE_FLOOR = 0.05
_CONFIDENCE_CAP = 0.95

# Keywords for direction classification
_BULLISH_RE = re.compile(
    r"\b(above|exceeds|exceed|over|new ath|higher than|hits|hit|reaches|reach|"
    r"breaks|break|crosses|cross|surpasses|surpass|gains|gain|rallies|rally)\b",
    re.IGNORECASE,
)
_BEARISH_RE = re.compile(
    r"\b(below|under|drops|drop|falls|fall|falls below|loses|lose|"
    r"declines|decline|crashes|crash|dips|dip|retreats|retreat)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Default parameters
# ---------------------------------------------------------------------------

_DEFAULT_PARAMS: dict[str, float] = {
    "direction_bullish_up_multiplier": 1.20,
    "direction_bullish_down_multiplier": 0.70,
    "direction_bearish_down_multiplier": 1.20,
    "direction_bearish_up_multiplier": 0.70,
    "rsi_overbought_multiplier": 0.85,
    "rsi_oversold_multiplier": 0.85,
    "macd_crossover_bonus": 0.05,
    "streak_bonus": 0.03,
    "volume_spike_bonus": 0.05,
    "volume_low_multiplier": 0.80,
    "proximity_close_multiplier": 0.75,
    "proximity_far_bonus": 0.08,
    "volatility_high_multiplier": 0.85,
    "atr_high_multiplier": 0.85,
}

_DEFAULT_FILE_CONTENT: dict = {
    "version": 1,
    "updated_at": None,
    "updated_by": "manual",
    "params": _DEFAULT_PARAMS,
    "performance": {
        "total_trades": 0,
        "win_rate": None,
        "avg_pnl_pct": None,
        "last_evaluated_at": None,
    },
}

# ---------------------------------------------------------------------------
# Parameter loading
# ---------------------------------------------------------------------------

def _params_path() -> str:
    return os.getenv("POLY_SIGNAL_PARAMS_PATH", "polymarket/signal_params.json")


def load_signal_params(path: str | None = None) -> dict[str, float]:
    """Read signal params from disk, fall back to defaults on any error.

    If the file is missing, writes the default structure (swallows OSError).
    Returns a dict of param_name → float value.
    """
    fpath = Path(path or _params_path())

    if not fpath.exists():
        # Write defaults so the file exists for future edits
        try:
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(
                json.dumps(_DEFAULT_FILE_CONTENT, indent=2), encoding="utf-8"
            )
            LOGGER.info("signals_params_created path=%s", fpath)
        except OSError as exc:
            LOGGER.warning("signals_params_write_failed path=%s error=%s", fpath, exc)
        return dict(_DEFAULT_PARAMS)

    try:
        raw = json.loads(fpath.read_text(encoding="utf-8"))
        params = raw.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("params key is not a dict")
        # Merge with defaults so new keys added later still work
        merged = dict(_DEFAULT_PARAMS)
        for k, v in params.items():
            if isinstance(v, (int, float)):
                merged[k] = float(v)
        LOGGER.debug("signals_params_loaded path=%s count=%d", fpath, len(merged))
        return merged
    except Exception as exc:
        LOGGER.warning(
            "signals_params_load_failed path=%s error=%s — using defaults", fpath, exc
        )
        return dict(_DEFAULT_PARAMS)


# Module-level mutable params dict — loaded once at import time
_PARAMS: dict[str, float] = load_signal_params()


def reload_signal_params() -> None:
    """Replace _PARAMS in-place from disk (atomic in CPython)."""
    global _PARAMS
    new = load_signal_params()
    _PARAMS = new
    LOGGER.info("signals_params_reloaded count=%d", len(new))


def get_signal_params() -> dict[str, float]:
    """Return a copy of the current active params."""
    return dict(_PARAMS)


# ---------------------------------------------------------------------------
# Direction classification
# ---------------------------------------------------------------------------

def classify_direction(opp: Opportunity) -> str:
    """Return 'bullish' | 'bearish' | 'neutral' for an opportunity.

    Orderbook spread (YES+NO) is always neutral — direction rules don't apply
    because we hold both sides and profit from mis-pricing alone.

    For correlated_markets and cross_market, infer from keywords in the
    question first, then fall back to the action string.
    """
    if opp.strategy == "orderbook_spread":
        return "neutral"

    q = opp.market_question

    if _BULLISH_RE.search(q):
        return "bullish"
    if _BEARISH_RE.search(q):
        return "bearish"

    # Secondary: action string (e.g. "buy YES" implies bullish on outcome)
    action_lower = opp.action.lower()
    if "buy yes" in action_lower:
        return "bullish"
    if "sell yes" in action_lower:
        return "bearish"

    return "neutral"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_opportunity(opp: Opportunity, signals: "BtcSignals") -> Opportunity:
    """Apply BTC signal rules to an opportunity and return an updated copy.

    Rules (in application order):
      Direction alignment  → multipliers based on 24h price change vs direction
      Momentum             → RSI, MACD crossover, consecutive-bar streak
      Volume               → volume ratio (spike or drought)
      Proximity            → distance of BTC price from market threshold
      Volatility           → Bollinger Band width ratio, ATR ratio

    Returns the *same* opportunity if signals.data_available is False or if
    scoring raises an unexpected exception (logged as WARNING).
    """
    if not signals.data_available:
        return opp

    try:
        return _apply_rules(opp, signals)
    except Exception as exc:
        LOGGER.warning(
            "signals_score_error strategy=%s market=%s error=%s — passing through unchanged",
            opp.strategy,
            opp.market_question[:60],
            exc,
        )
        return opp


def _apply_rules(opp: Opportunity, signals: "BtcSignals") -> Opportunity:
    p = _PARAMS
    score = _CONFIDENCE_MAP.get(opp.confidence, 0.50)
    notes: list[str] = []

    direction = opp.direction if opp.direction else classify_direction(opp)
    change_24h = signals.change_24h_pct

    # ------------------------------------------------------------------
    # 1. Direction alignment — most important rules
    # ------------------------------------------------------------------
    if direction == "bullish":
        if change_24h > 3.0:
            mul = p["direction_bullish_up_multiplier"]
            score *= mul
            notes.append(f"direction_aligned_bullish change_24h={change_24h:+.1f}% ×{mul:.2f}")
        elif change_24h < -3.0:
            mul = p["direction_bullish_down_multiplier"]
            score *= mul
            notes.append(f"direction_opposed_bullish change_24h={change_24h:+.1f}% ×{mul:.2f}")
    elif direction == "bearish":
        if change_24h < -3.0:
            mul = p["direction_bearish_down_multiplier"]
            score *= mul
            notes.append(f"direction_aligned_bearish change_24h={change_24h:+.1f}% ×{mul:.2f}")
        elif change_24h > 3.0:
            mul = p["direction_bearish_up_multiplier"]
            score *= mul
            notes.append(f"direction_opposed_bearish change_24h={change_24h:+.1f}% ×{mul:.2f}")

    # ------------------------------------------------------------------
    # 2. Momentum — RSI
    # ------------------------------------------------------------------
    rsi = signals.rsi_14
    if rsi > 70 and direction == "bullish":
        # Overbought — mean reversion risk when betting on continued up-move
        mul = p["rsi_overbought_multiplier"]
        score *= mul
        notes.append(f"rsi_overbought rsi={rsi:.1f} ×{mul:.2f}")
    elif rsi < 30 and direction == "bearish":
        # Oversold — mean reversion risk when betting on continued down-move
        mul = p["rsi_oversold_multiplier"]
        score *= mul
        notes.append(f"rsi_oversold rsi={rsi:.1f} ×{mul:.2f}")

    # ------------------------------------------------------------------
    # 3. Momentum — MACD crossover
    # ------------------------------------------------------------------
    if signals.macd_crossover == "bullish" and direction == "bullish":
        bonus = p["macd_crossover_bonus"]
        score += bonus
        notes.append(f"macd_bullish_crossover +{bonus:.2f}")

    # ------------------------------------------------------------------
    # 4. Momentum — consecutive bar streak
    # ------------------------------------------------------------------
    streak = signals.consecutive_bars
    streak_dir = signals.streak_direction
    if streak >= 4 and streak_dir == "green" and direction == "bullish":
        bonus = p["streak_bonus"]
        score += bonus
        notes.append(f"green_streak streak={streak} +{bonus:.2f}")

    # ------------------------------------------------------------------
    # 5. Volume
    # ------------------------------------------------------------------
    vol_ratio = signals.volume_ratio
    if vol_ratio > 2.0:
        # High-conviction move regardless of direction
        bonus = p["volume_spike_bonus"]
        score += bonus
        notes.append(f"volume_spike ratio={vol_ratio:.1f} +{bonus:.2f}")
    elif vol_ratio < 0.5:
        # Low liquidity / conviction — widen skepticism
        mul = p["volume_low_multiplier"]
        score *= mul
        notes.append(f"volume_low ratio={vol_ratio:.1f} ×{mul:.2f}")

    # ------------------------------------------------------------------
    # 6. Proximity — distance from market threshold
    # ------------------------------------------------------------------
    threshold = _extract_usd_threshold(opp.market_question)
    price = signals.price_usd
    if threshold and threshold > 0 and price > 0:
        dist_pct = (price - threshold) / threshold * 100.0
        abs_dist = abs(dist_pct)

        if abs_dist < 2.0:
            # Price within 2% of threshold — too close to call
            mul = p["proximity_close_multiplier"]
            score *= mul
            notes.append(
                f"threshold_proximity price={price:.0f} threshold={threshold:.0f}"
                f" dist={dist_pct:+.1f}% ×{mul:.2f}"
            )
        elif direction in ("bullish", "bearish"):
            # Determine if distance is favourable for the direction
            favourable = (direction == "bullish" and price > threshold) or \
                         (direction == "bearish" and price < threshold)
            if favourable and abs_dist > 20.0:
                # High certainty the market has already resolved in our favour
                bonus = p["proximity_far_bonus"]
                score += bonus
                notes.append(
                    f"threshold_clearance dist={dist_pct:+.1f}% +{bonus:.2f}"
                )

    # ------------------------------------------------------------------
    # 7. Volatility — Bollinger Band width
    # ------------------------------------------------------------------
    bb = signals.bb_width_ratio
    if bb > 2.0:
        mul = p["volatility_high_multiplier"]
        score *= mul
        notes.append(f"high_volatility bb_width_ratio={bb:.2f} ×{mul:.2f}")

    # ------------------------------------------------------------------
    # 8. Volatility — ATR ratio
    # ------------------------------------------------------------------
    atr = signals.atr_ratio
    if atr > 1.5:
        mul = p["atr_high_multiplier"]
        score *= mul
        notes.append(f"high_atr atr_ratio={atr:.2f} ×{mul:.2f}")

    # ------------------------------------------------------------------
    # Finalise
    # ------------------------------------------------------------------
    final_score = max(_CONFIDENCE_FLOOR, min(_CONFIDENCE_CAP, score))
    rank = final_score * opp.edge_pct

    if not notes:
        notes.append("no_signal_rules_triggered")

    return dataclasses.replace(
        opp,
        direction=direction,
        confidence_score=round(final_score, 4),
        rank_score=round(rank, 4),
        signal_notes=tuple(notes),
    )
