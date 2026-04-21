"""Autonomous AI analysis loop — scheduled runs with confidence-tiered apply logic.

Designed for Render: all state in Postgres, safe to restart at any time.

Confidence tiers:
  >= 0.90 AND impact <= 10%  → auto-apply immediately
  0.75-0.89 OR impact 10-20% → queue, auto-apply after POLY_AI_AUTO_APPLY_HOURS
  < 0.75                     → queue, require manual approval
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

LOGGER = logging.getLogger("trauto.ai.loop")

_AI_ANALYSIS_INTERVAL_HOURS = float(os.getenv("AI_ANALYSIS_INTERVAL_HOURS", "24"))
_AI_AUTO_APPLY_HOURS = float(os.getenv("POLY_AI_AUTO_APPLY_HOURS", "4"))
_AI_CIRCUIT_BREAKER_HOURS = 6.0   # min hours between analysis runs
_AI_MONTHLY_TOKEN_BUDGET = int(os.getenv("AI_MONTHLY_TOKEN_BUDGET", "100000"))
_AI_CHECK_INTERVAL_SECONDS = 3600  # how often the loop wakes to check

# Confidence thresholds
_CONF_AUTO_APPLY = 0.90
_CONF_QUEUE_WITH_TIMER = 0.75
_IMPACT_AUTO_APPLY_MAX = 0.10   # 10%
_IMPACT_TIMER_MAX = 0.20        # 20%


async def background_loop(db_url: str) -> None:
    """Asyncio background task — runs forever, checks analysis schedule each hour."""
    LOGGER.info("ai_loop_started interval_hours=%.1f", _AI_ANALYSIS_INTERVAL_HOURS)
    while True:
        try:
            await asyncio.to_thread(_run_scheduled_analysis, db_url)
        except Exception as exc:
            LOGGER.error("ai_loop_error error=%s", exc)
        await asyncio.sleep(_AI_CHECK_INTERVAL_SECONDS)


def _run_scheduled_analysis(db_url: str, force: bool = False) -> dict[str, Any]:
    """Check schedule and run analysis if due. Returns result summary."""
    from trauto.ai.db import AIRepository
    from src.persistence.store import DatabaseStore

    store = DatabaseStore(database_url=db_url)
    repo = AIRepository(store=store)

    # Schema bootstrap (idempotent)
    repo.ensure_schema()
    repo.seed_signal_params_if_needed()

    # Auto-apply any proposals whose timer has elapsed
    applied_ids = repo.apply_due_auto_proposals()
    if applied_ids:
        LOGGER.info("ai_auto_applied proposal_ids=%s", applied_ids)

    if not force:
        # Circuit breaker: skip if last analysis was < 6 hours ago
        last_at = repo.get_last_analysis_at()
        if last_at:
            hours_since = (datetime.now(tz=timezone.utc) - last_at).total_seconds() / 3600
            if hours_since < _AI_CIRCUIT_BREAKER_HOURS:
                LOGGER.debug(
                    "ai_analysis_skipped reason=circuit_breaker hours_since=%.1f", hours_since
                )
                return {"skipped": True, "reason": "circuit_breaker", "hours_since": hours_since}

            if hours_since < _AI_ANALYSIS_INTERVAL_HOURS:
                LOGGER.debug(
                    "ai_analysis_skipped reason=not_due hours_since=%.1f", hours_since
                )
                return {"skipped": True, "reason": "not_due", "hours_since": hours_since}

        # Skip if pending proposal already exists
        if repo.has_pending_proposal():
            LOGGER.info("ai_analysis_skipped reason=pending_proposal_exists")
            return {"skipped": True, "reason": "pending_proposal"}

    # Monthly token budget check
    used = repo.get_monthly_token_usage()
    if used >= _AI_MONTHLY_TOKEN_BUDGET:
        LOGGER.warning(
            "ai_analysis_skipped reason=monthly_token_budget_exceeded used=%d budget=%d",
            used, _AI_MONTHLY_TOKEN_BUDGET,
        )
        return {"skipped": True, "reason": "token_budget_exceeded", "tokens_used": used}

    return _execute_analysis(repo)


def _execute_analysis(repo: "AIRepository") -> dict[str, Any]:
    """Run the full analysis pipeline and apply/queue result."""
    from trauto.ai.analyst import analyze, AIAnalysis
    from trauto.ai.validator import SafetyValidator, compute_change_impact

    t0 = time.monotonic()

    # Load inputs
    fills = repo.load_recent_fills(days=30)
    current_params = repo.load_signal_params()

    btc_signals = None
    try:
        from src.polymarket.alpaca_signals import get_cached_signals
        btc_signals = get_cached_signals()
    except Exception:
        pass

    input_summary = {
        "fills_count": len(fills),
        "params_count": len(current_params),
        "btc_available": btc_signals is not None,
    }

    LOGGER.info(
        "ai_analysis_start fills=%d params=%d btc=%s",
        len(fills), len(current_params), btc_signals is not None,
    )

    # Call analyst
    analysis = analyze(fills, current_params, btc_signals)
    if analysis is None:
        repo.create_analysis_log(
            analysis_type="parameter_tuning",
            input_summary=input_summary,
            output_summary={"outcome": "analyst_returned_none"},
        )
        return {"outcome": "analyst_failed"}

    # Validate
    validator = SafetyValidator()
    safe_analysis = validator.validate(analysis, current_params)

    outcome: str
    proposal_id: int | None = None

    if safe_analysis is None:
        outcome = "safety_rejected"
        LOGGER.warning("ai_analysis_safety_rejected confidence=%.2f", analysis.confidence)
    else:
        analysis = safe_analysis
        impact = compute_change_impact(analysis.proposed_params, current_params)
        outcome, proposal_id = _apply_or_queue(repo, analysis, current_params, impact)

    # Track monthly token usage
    if analysis.tokens_used:
        new_total = repo.add_monthly_token_usage(analysis.tokens_used)
        LOGGER.info("ai_monthly_tokens_used total=%d", new_total)

    duration_ms = int((time.monotonic() - t0) * 1000)
    output_summary = {
        "outcome": outcome,
        "confidence": analysis.confidence,
        "trade_count": analysis.trade_count_analyzed,
        "win_rate": analysis.win_rate,
        "avg_pnl_pct": analysis.avg_pnl_pct,
        "proposal_id": proposal_id,
        "tokens_used": analysis.tokens_used,
    }

    repo.create_analysis_log(
        analysis_type="parameter_tuning",
        input_summary=input_summary,
        output_summary=output_summary,
        tokens_used=analysis.tokens_used,
        duration_ms=duration_ms,
    )

    LOGGER.info(
        "ai_analysis_complete outcome=%s confidence=%.2f trade_count=%d proposal_id=%s duration_ms=%d",
        outcome, analysis.confidence, analysis.trade_count_analyzed, proposal_id, duration_ms,
    )
    return output_summary


def _apply_or_queue(
    repo: "AIRepository",
    analysis: "AIAnalysis",
    current_params: dict[str, float],
    impact: float,
) -> tuple[str, int | None]:
    """Decide whether to auto-apply immediately, queue with timer, or queue for manual."""
    from trauto.ai.validator import compute_change_impact

    conf = analysis.confidence

    # Tier 1: high confidence, low impact → auto-apply immediately
    if conf >= _CONF_AUTO_APPLY and impact <= _IMPACT_AUTO_APPLY_MAX:
        proposal_id = repo.create_proposal(
            current_params=current_params,
            proposed_params=analysis.proposed_params,
            reasoning=analysis.reasoning,
            confidence=conf,
            trade_count=analysis.trade_count_analyzed,
            win_rate=analysis.win_rate,
            avg_pnl_pct=analysis.avg_pnl_pct,
            key_findings=analysis.key_findings,
            warnings=analysis.warnings,
            proposal_type="parameter_tuning",
            auto_apply_hours=None,  # immediately
        )
        if repo.apply_proposal(proposal_id, applied_by="ai_auto_high_confidence"):
            LOGGER.info(
                "ai_auto_applied_immediately proposal_id=%d reason=high_confidence impact=%.2f",
                proposal_id, impact,
            )
            return "auto_applied", proposal_id
        return "apply_failed", proposal_id

    # Tier 2: moderate confidence or impact → queue with timer
    if conf >= _CONF_QUEUE_WITH_TIMER or (conf >= _CONF_AUTO_APPLY and impact <= _IMPACT_TIMER_MAX):
        proposal_id = repo.create_proposal(
            current_params=current_params,
            proposed_params=analysis.proposed_params,
            reasoning=analysis.reasoning,
            confidence=conf,
            trade_count=analysis.trade_count_analyzed,
            win_rate=analysis.win_rate,
            avg_pnl_pct=analysis.avg_pnl_pct,
            key_findings=analysis.key_findings,
            warnings=analysis.warnings,
            proposal_type="parameter_tuning",
            auto_apply_hours=_AI_AUTO_APPLY_HOURS,
        )
        LOGGER.info(
            "ai_proposal_queued_with_timer proposal_id=%d confidence=%.2f auto_apply_hours=%.1f",
            proposal_id, conf, _AI_AUTO_APPLY_HOURS,
        )
        return "queued_with_timer", proposal_id

    # Tier 3: low confidence → queue for manual approval only
    proposal_id = repo.create_proposal(
        current_params=current_params,
        proposed_params=analysis.proposed_params,
        reasoning=analysis.reasoning,
        confidence=conf,
        trade_count=analysis.trade_count_analyzed,
        win_rate=analysis.win_rate,
        avg_pnl_pct=analysis.avg_pnl_pct,
        key_findings=analysis.key_findings,
        warnings=analysis.warnings,
        proposal_type="parameter_tuning",
        auto_apply_hours=None,  # manual only
    )
    LOGGER.info(
        "ai_proposal_queued_manual proposal_id=%d confidence=%.2f",
        proposal_id, conf,
    )
    return "queued_manual", proposal_id


def run_commentary(db_url: str, portfolio_snapshot: dict | None = None) -> str:
    """Generate and store daily AI commentary. Returns the generated text."""
    from trauto.ai.analyst import generate_commentary
    from trauto.ai.db import AIRepository
    from src.persistence.store import DatabaseStore

    btc_signals = None
    try:
        from src.polymarket.alpaca_signals import get_cached_signals
        btc_signals = get_cached_signals()
    except Exception:
        pass

    text = generate_commentary(portfolio_snapshot, btc_signals)
    if not text:
        return ""

    store = DatabaseStore(database_url=db_url)
    repo = AIRepository(store=store)

    from datetime import datetime, timezone
    repo.set_kv("daily_commentary", {
        "text": text,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "model": "claude-sonnet-4-20250514",
    })
    LOGGER.info("ai_commentary_stored length=%d", len(text))
    return text


def trigger_immediate_analysis(db_url: str) -> dict:
    """Trigger an immediate analysis run (bypasses schedule check). For API/dashboard."""
    from trauto.ai.db import AIRepository
    from src.persistence.store import DatabaseStore

    store = DatabaseStore(database_url=db_url)
    repo = AIRepository(store=store)
    repo.ensure_schema()
    repo.seed_signal_params_if_needed()
    return _execute_analysis(repo)
