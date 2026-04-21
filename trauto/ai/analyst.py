"""AI analyst — calls Anthropic API to analyze trade history and propose param changes.

Never raises exceptions. All failures return None and log the error.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

LOGGER = logging.getLogger("trauto.ai.analyst")

_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS_ANALYSIS = 1000
_MAX_TOKENS_COMMENTARY = 300

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

_SYSTEM_PROMPT = """\
You are a quantitative trading analyst for Trauto, an algorithmic trading bot. \
You analyze prediction market trade history and propose improvements to signal scoring parameters.

You must respond ONLY with valid JSON matching this exact schema:
{
  "proposed_params": { "<param_name>": <float_value> },
  "reasoning": "<plain english explanation of changes>",
  "confidence": <0.0-1.0>,
  "key_findings": ["<finding 1>", "<finding 2>"],
  "warnings": ["<warning 1>"],
  "win_rate": <0.0-1.0>,
  "avg_pnl_pct": <float>
}

Parameter bounds you must respect:
- Multipliers (direction_*, rsi_*, volume_low_multiplier, proximity_close_multiplier, volatility_high_multiplier, atr_high_multiplier): min 0.50, max 1.50
- Bonuses (macd_crossover_bonus, streak_bonus, volume_spike_bonus, proximity_far_bonus): min 0.00, max 0.15
- Never change more than 3 parameters in one proposal
- Never adjust a parameter by more than 20% from its current value
- Only propose changes for parameters with 10 or more supporting trades
- If there is insufficient data to make recommendations, return the current_params unchanged and set confidence below 0.60"""


@dataclass
class AIAnalysis:
    """Output of the AI analyst."""
    proposed_params: dict[str, float]
    reasoning: str
    confidence: float
    key_findings: list[str]
    warnings: list[str]
    trade_count_analyzed: int
    win_rate: float
    avg_pnl_pct: float
    tokens_used: int = 0
    duration_ms: int = 0


def analyze(
    fills: list[dict[str, Any]],
    current_params: dict[str, float],
    btc_signals: Any | None = None,
) -> AIAnalysis | None:
    """Call Anthropic API to analyze trade history and propose parameter changes.

    Returns None on any failure — never crashes the caller.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        LOGGER.warning("ai_analyst_skipped reason=ANTHROPIC_API_KEY_not_set")
        return None

    try:
        import anthropic
    except ImportError:
        LOGGER.error("ai_analyst_skipped reason=anthropic_package_not_installed")
        return None

    # Build trade summary
    trade_summary = _summarize_fills(fills)
    if trade_summary["total_fills"] == 0:
        LOGGER.info("ai_analyst_skipped reason=no_fills_in_window")
        return None

    # Build BTC context
    btc_context = _format_btc_context(btc_signals)

    # Build user prompt
    user_prompt = _build_user_prompt(trade_summary, current_params, btc_context)

    start_ms = int(time.monotonic() * 1000)
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS_ANALYSIS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        duration_ms = int(time.monotonic() * 1000) - start_ms
        tokens_used = (
            response.usage.input_tokens + response.usage.output_tokens
            if hasattr(response, "usage")
            else 0
        )
        raw_text = response.content[0].text if response.content else ""
    except Exception as exc:
        LOGGER.error("ai_analyst_api_error error=%s", exc)
        return None

    # Parse and validate JSON response
    analysis = _parse_response(raw_text, current_params, trade_summary, tokens_used, duration_ms)
    if analysis is None:
        LOGGER.error("ai_analyst_parse_failed raw_length=%d", len(raw_text))
    return analysis


def generate_commentary(
    portfolio_snapshot: dict[str, Any] | None = None,
    btc_signals: Any | None = None,
) -> str:
    """Generate a 3-4 sentence daily strategy commentary. Returns empty string on failure."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return ""

    try:
        import anthropic
    except ImportError:
        return ""

    portfolio_str = "No portfolio data available."
    if portfolio_snapshot:
        portfolio_str = (
            f"Total value: ${portfolio_snapshot.get('total_value', 0):.2f}, "
            f"daily P&L: ${portfolio_snapshot.get('daily_pnl', 0):.2f}, "
            f"open positions: {portfolio_snapshot.get('open_positions', 0)}, "
            f"realized P&L today: ${portfolio_snapshot.get('realized_pnl_today', 0):.2f}"
        )

    btc_str = _format_btc_context(btc_signals)

    prompt = (
        f"Portfolio state: {portfolio_str}\n"
        f"BTC market context: {btc_str}\n\n"
        "In 3-4 sentences, summarize the current state of this prediction market trading "
        "portfolio and give one specific actionable observation. Be direct and concise."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS_COMMENTARY,
            system=(
                "You are a trading analyst. Provide brief, factual commentary on prediction "
                "market trading performance. No jargon, no fluff."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip() if response.content else ""
    except Exception as exc:
        LOGGER.error("ai_commentary_error error=%s", exc)
        return ""


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _summarize_fills(fills: list[dict[str, Any]]) -> dict[str, Any]:
    """Build trade summary statistics from raw fill records."""
    by_symbol: dict[str, list[dict]] = {}
    for f in fills:
        by_symbol.setdefault(f["symbol"], []).append(f)

    total_pnl = 0.0
    closed_trades = 0
    wins = 0
    by_side: dict[str, int] = {"buy": 0, "sell": 0}

    for symbol, sym_fills in by_symbol.items():
        buys = [f for f in sym_fills if f["side"].lower() in ("buy", "long")]
        sells = [f for f in sym_fills if f["side"].lower() in ("sell", "short")]
        if buys and sells:
            buy_notional = sum(f["notional"] for f in buys)
            sell_notional = sum(f["notional"] for f in sells)
            pnl = sell_notional - buy_notional
            total_pnl += pnl
            closed_trades += 1
            if pnl > 0:
                wins += 1

        for f in sym_fills:
            side = f["side"].lower()
            if side in ("buy", "long"):
                by_side["buy"] += 1
            else:
                by_side["sell"] += 1

    total_notional = sum(f["notional"] for f in fills)
    avg_pnl_pct = (total_pnl / total_notional * 100) if total_notional > 0 and closed_trades > 0 else 0.0
    win_rate = wins / closed_trades if closed_trades > 0 else 0.0

    return {
        "total_fills": len(fills),
        "closed_trades": closed_trades,
        "wins": wins,
        "losses": closed_trades - wins,
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 4),
        "avg_pnl_pct": round(avg_pnl_pct, 4),
        "symbols_traded": len(by_symbol),
        "by_side": by_side,
    }


def _format_btc_context(btc_signals: Any) -> str:
    if btc_signals is None:
        return "BTC signals unavailable"
    try:
        return (
            f"24h change: {btc_signals.price_change_24h_pct:.2f}%, "
            f"RSI: {btc_signals.rsi:.1f}, "
            f"volume ratio: {btc_signals.volume_ratio:.2f}, "
            f"bias: {btc_signals.bias}"
        )
    except AttributeError:
        return str(btc_signals)


def _build_user_prompt(
    summary: dict[str, Any],
    current_params: dict[str, float],
    btc_context: str,
) -> str:
    params_str = json.dumps(current_params, indent=2)
    n = summary["closed_trades"]
    win_rate_pct = summary["win_rate"] * 100
    return (
        f"Analyze these {n} closed trades from the last 30 days and propose "
        f"improvements to the signal scoring parameters.\n\n"
        f"Current parameters:\n{params_str}\n\n"
        f"Trade history summary:\n"
        f"- Total fills: {summary['total_fills']}\n"
        f"- Closed trade pairs: {n}\n"
        f"- Win rate: {win_rate_pct:.1f}%\n"
        f"- Avg P&L: {summary['avg_pnl_pct']:.2f}%\n"
        f"- Total P&L: ${summary['total_pnl']:.2f}\n"
        f"- Symbols traded: {summary['symbols_traded']}\n"
        f"- Buys: {summary['by_side'].get('buy', 0)}, "
        f"Sells: {summary['by_side'].get('sell', 0)}\n\n"
        f"Recent BTC market context:\n{btc_context}\n\n"
        f"Based on this data, propose parameter adjustments if the evidence supports it. "
        f"Return ONLY the JSON response matching the schema in the system prompt."
    )


def _parse_response(
    raw: str,
    current_params: dict[str, float],
    summary: dict[str, Any],
    tokens_used: int,
    duration_ms: int,
) -> AIAnalysis | None:
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        LOGGER.error("ai_response_json_parse_failed error=%s raw_preview=%.200s", exc, raw)
        return None

    # Extract and coerce proposed_params
    proposed_raw = data.get("proposed_params", {})
    if not isinstance(proposed_raw, dict):
        LOGGER.error("ai_response_proposed_params_not_dict type=%s", type(proposed_raw))
        return None

    # Build proposed params: start from current, apply AI changes for known keys only
    proposed: dict[str, float] = dict(current_params)
    known_params = _MULTIPLIER_PARAMS | _BONUS_PARAMS
    for k, v in proposed_raw.items():
        if k in known_params:
            try:
                proposed[k] = float(v)
            except (TypeError, ValueError):
                LOGGER.warning("ai_response_invalid_param_value param=%s value=%s", k, v)

    confidence = float(data.get("confidence", 0.0))
    reasoning = str(data.get("reasoning", ""))
    key_findings = [str(f) for f in data.get("key_findings", [])]
    warnings_list = [str(w) for w in data.get("warnings", [])]

    return AIAnalysis(
        proposed_params=proposed,
        reasoning=reasoning,
        confidence=confidence,
        key_findings=key_findings,
        warnings=warnings_list,
        trade_count_analyzed=summary["closed_trades"],
        win_rate=summary["win_rate"],
        avg_pnl_pct=summary["avg_pnl_pct"],
        tokens_used=tokens_used,
        duration_ms=duration_ms,
    )
