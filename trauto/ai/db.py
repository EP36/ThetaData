"""DB operations for Phase 7 AI tables.

Follows the same DatabaseStore / session-context pattern as the rest of the
persistence layer.  All methods are synchronous (called from sync context in
the background loop; FastAPI endpoints call them via run_in_executor if needed).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select

from src.persistence.models import (
    AIAnalysisLogModel,
    AIProposalModel,
    SignalParamsModel,
    StrategyConfigModel,
    utc_now,
)
from src.persistence.store import DatabaseStore

LOGGER = logging.getLogger("trauto.ai.db")

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

_KV_PREFIX = "__ai__"


def _make_store() -> DatabaseStore:
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL env var not set")
    return DatabaseStore(database_url=db_url)


class AIRepository:
    """All AI-specific DB reads/writes."""

    def __init__(self, store: DatabaseStore | None = None) -> None:
        self._store = store or _make_store()

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def ensure_schema(self) -> None:
        """Idempotent: create AI tables if they don't exist."""
        from src.persistence.models import Base
        Base.metadata.create_all(self._store.engine)

    # ------------------------------------------------------------------
    # signal_params
    # ------------------------------------------------------------------

    def seed_signal_params_if_needed(self) -> bool:
        """Seed signal_params row from JSON defaults if the table is empty.

        Idempotent — safe to call on every startup.  Returns True if seeded.
        """
        with self._store.session() as session:
            existing = session.scalar(select(SignalParamsModel).limit(1))
            if existing is not None:
                return False

            # Try to load from the legacy JSON file first
            params = dict(_DEFAULT_PARAMS)
            performance: dict[str, Any] = {
                "total_trades": 0,
                "win_rate": None,
                "avg_pnl_pct": None,
                "last_evaluated_at": None,
            }
            try:
                import json
                from pathlib import Path
                path = os.getenv("POLY_SIGNAL_PARAMS_PATH", "polymarket/signal_params.json")
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                if isinstance(data.get("params"), dict):
                    for k, v in data["params"].items():
                        if isinstance(v, (int, float)):
                            params[k] = float(v)
                if isinstance(data.get("performance"), dict):
                    performance = data["performance"]
                LOGGER.info("ai_db_seed_signal_params_from_json path=%s", path)
            except Exception as exc:
                LOGGER.info("ai_db_seed_signal_params_defaults reason=%s", exc)

            row = SignalParamsModel(
                version=1,
                params=params,
                performance=performance,
                updated_by="seed",
            )
            session.add(row)
            LOGGER.info("ai_db_signal_params_seeded param_count=%d", len(params))
            return True

    def load_signal_params(self) -> dict[str, float]:
        """Load the latest signal params from DB. Falls back to defaults."""
        with self._store.session() as session:
            row = session.scalar(
                select(SignalParamsModel).order_by(desc(SignalParamsModel.id)).limit(1)
            )
            if row is None:
                return dict(_DEFAULT_PARAMS)
            merged = dict(_DEFAULT_PARAMS)
            for k, v in (row.params or {}).items():
                if isinstance(v, (int, float)):
                    merged[k] = float(v)
            return merged

    def load_signal_params_full(self) -> dict[str, Any]:
        """Return the full signal_params row as a dict."""
        with self._store.session() as session:
            row = session.scalar(
                select(SignalParamsModel).order_by(desc(SignalParamsModel.id)).limit(1)
            )
            if row is None:
                return {"version": 1, "params": dict(_DEFAULT_PARAMS), "performance": {}, "updated_by": "default"}
            return {
                "id": row.id,
                "version": row.version,
                "params": row.params,
                "performance": row.performance,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "updated_by": row.updated_by,
            }

    def save_signal_params(
        self,
        params: dict[str, float],
        performance: dict[str, Any] | None = None,
        updated_by: str = "ai",
    ) -> None:
        """Persist new signal params (inserts a new versioned row)."""
        with self._store.session() as session:
            last = session.scalar(
                select(SignalParamsModel).order_by(desc(SignalParamsModel.id)).limit(1)
            )
            next_version = (last.version + 1) if last else 1
            row = SignalParamsModel(
                version=next_version,
                params=params,
                performance=performance,
                updated_by=updated_by,
            )
            session.add(row)
            LOGGER.info(
                "ai_db_signal_params_saved version=%d updated_by=%s param_count=%d",
                next_version,
                updated_by,
                len(params),
            )

    # ------------------------------------------------------------------
    # ai_proposals
    # ------------------------------------------------------------------

    def create_proposal(
        self,
        current_params: dict[str, float],
        proposed_params: dict[str, float],
        reasoning: str,
        confidence: float,
        trade_count: int,
        win_rate: float,
        avg_pnl_pct: float,
        key_findings: list[str],
        warnings: list[str],
        proposal_type: str = "parameter_tuning",
        auto_apply_hours: float | None = None,
    ) -> int:
        """Insert a new proposal row. Returns the new id."""
        auto_apply_after: datetime | None = None
        if auto_apply_hours is not None:
            auto_apply_after = utc_now() + timedelta(hours=auto_apply_hours)
        with self._store.session() as session:
            row = AIProposalModel(
                status="pending",
                proposal_type=proposal_type,
                current_params=current_params,
                proposed_params=proposed_params,
                reasoning=reasoning,
                trade_count=trade_count,
                win_rate=win_rate,
                avg_pnl_pct=avg_pnl_pct,
                confidence=confidence,
                key_findings=key_findings,
                warnings=warnings,
                auto_apply_after=auto_apply_after,
            )
            session.add(row)
            session.flush()
            proposal_id = int(row.id)
            LOGGER.info(
                "ai_db_proposal_created id=%d confidence=%.2f auto_apply_after=%s",
                proposal_id,
                confidence,
                auto_apply_after,
            )
            return proposal_id

    def get_proposal(self, proposal_id: int) -> dict[str, Any] | None:
        with self._store.session() as session:
            row = session.get(AIProposalModel, proposal_id)
            return _proposal_to_dict(row) if row else None

    def list_proposals(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._store.session() as session:
            rows = session.scalars(
                select(AIProposalModel)
                .order_by(desc(AIProposalModel.created_at))
                .limit(limit)
            ).all()
            return [_proposal_to_dict(r) for r in rows]

    def has_pending_proposal(self) -> bool:
        with self._store.session() as session:
            row = session.scalar(
                select(AIProposalModel)
                .where(AIProposalModel.status == "pending")
                .limit(1)
            )
            return row is not None

    def apply_proposal(self, proposal_id: int, applied_by: str = "ai_auto") -> bool:
        """Mark proposal as applied and write new signal params. Returns True on success."""
        with self._store.session() as session:
            row = session.get(AIProposalModel, proposal_id)
            if row is None or row.status != "pending":
                return False
            row.status = "applied"
            row.applied_at = utc_now()
            row.applied_by = applied_by
            proposed = dict(row.proposed_params or {})
            current = dict(row.current_params or {})
            version_row = session.scalar(
                select(SignalParamsModel).order_by(desc(SignalParamsModel.id)).limit(1)
            )
            next_version = (version_row.version + 1) if version_row else 1
            new_params_row = SignalParamsModel(
                version=next_version,
                params=proposed,
                performance={
                    "trade_count": row.trade_count,
                    "win_rate": row.win_rate,
                    "avg_pnl_pct": row.avg_pnl_pct,
                    "applied_from_proposal_id": proposal_id,
                },
                updated_by=applied_by,
            )
            session.add(new_params_row)

            # Log changes
            for param, new_val in proposed.items():
                old_val = current.get(param, "?")
                if old_val != new_val:
                    LOGGER.info(
                        "ai_param_applied param=%s old=%s new=%s proposal_id=%d",
                        param, old_val, new_val, proposal_id,
                    )

            # Reload in-process params so running scorer picks them up
            try:
                from src.polymarket.signals import reload_signal_params
                reload_signal_params()
            except Exception as exc:
                LOGGER.warning("ai_signal_reload_failed error=%s", exc)

            return True

    def reject_proposal(self, proposal_id: int) -> bool:
        with self._store.session() as session:
            row = session.get(AIProposalModel, proposal_id)
            if row is None or row.status != "pending":
                return False
            row.status = "rejected"
            row.rejected_at = utc_now()
            LOGGER.info("ai_db_proposal_rejected id=%d", proposal_id)
            return True

    def apply_due_auto_proposals(self) -> list[int]:
        """Apply any pending proposals whose auto_apply_after has passed."""
        applied: list[int] = []
        now = utc_now()
        with self._store.session() as session:
            rows = session.scalars(
                select(AIProposalModel)
                .where(AIProposalModel.status == "pending")
                .where(AIProposalModel.auto_apply_after <= now)
            ).all()
            ids = [int(r.id) for r in rows]

        for proposal_id in ids:
            try:
                if self.apply_proposal(proposal_id, applied_by="ai_auto_timer"):
                    applied.append(proposal_id)
                    LOGGER.info("ai_auto_apply_executed proposal_id=%d", proposal_id)
            except Exception as exc:
                LOGGER.error("ai_auto_apply_failed proposal_id=%d error=%s", proposal_id, exc)
        return applied

    # ------------------------------------------------------------------
    # ai_analysis_log
    # ------------------------------------------------------------------

    def create_analysis_log(
        self,
        analysis_type: str,
        input_summary: dict[str, Any],
        output_summary: dict[str, Any],
        tokens_used: int = 0,
        duration_ms: int = 0,
        model: str = "claude-sonnet-4-20250514",
    ) -> int:
        with self._store.session() as session:
            row = AIAnalysisLogModel(
                analysis_type=analysis_type,
                input_summary=input_summary,
                output_summary=output_summary,
                tokens_used=tokens_used,
                duration_ms=duration_ms,
                model=model,
            )
            session.add(row)
            session.flush()
            log_id = int(row.id)
            LOGGER.info(
                "ai_analysis_logged id=%d type=%s tokens=%d duration_ms=%d",
                log_id, analysis_type, tokens_used, duration_ms,
            )
            return log_id

    def list_analysis_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._store.session() as session:
            rows = session.scalars(
                select(AIAnalysisLogModel)
                .order_by(desc(AIAnalysisLogModel.created_at))
                .limit(limit)
            ).all()
            return [_log_to_dict(r) for r in rows]

    def list_analysis_log(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent analysis log entries with key fields extracted from output_summary."""
        with self._store.session() as session:
            rows = session.scalars(
                select(AIAnalysisLogModel)
                .order_by(desc(AIAnalysisLogModel.created_at))
                .limit(limit)
            ).all()
            result = []
            for r in rows:
                out = r.output_summary or {}
                result.append({
                    "id": r.id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "analysis_type": r.analysis_type,
                    "outcome": out.get("outcome"),
                    "trade_count": out.get("trade_count"),
                    "win_rate": out.get("win_rate"),
                    "avg_pnl_pct": out.get("avg_pnl_pct"),
                    "confidence": out.get("confidence"),
                    "proposal_id": out.get("proposal_id"),
                    "tokens_used": r.tokens_used,
                    "duration_ms": r.duration_ms,
                })
            return result

    def get_last_analysis_at(self) -> datetime | None:
        with self._store.session() as session:
            row = session.scalar(
                select(AIAnalysisLogModel)
                .where(AIAnalysisLogModel.analysis_type == "parameter_tuning")
                .order_by(desc(AIAnalysisLogModel.created_at))
                .limit(1)
            )
            return row.created_at if row else None

    # ------------------------------------------------------------------
    # Monthly token budget (stored in StrategyConfigModel as KV)
    # ------------------------------------------------------------------

    def _kv_key(self, key: str) -> str:
        return f"{_KV_PREFIX}{key}"

    def get_kv(self, key: str) -> Any:
        with self._store.session() as session:
            row = session.get(StrategyConfigModel, self._kv_key(key))
            return row.parameters if row else None

    def set_kv(self, key: str, value: Any) -> None:
        with self._store.session() as session:
            full_key = self._kv_key(key)
            row = session.get(StrategyConfigModel, full_key)
            if row is None:
                row = StrategyConfigModel(name=full_key, parameters=value)
                session.add(row)
            else:
                row.parameters = value

    def get_monthly_token_usage(self) -> int:
        now = datetime.now(tz=timezone.utc)
        key = f"token_usage_{now.year}_{now.month:02d}"
        val = self.get_kv(key)
        return int(val.get("tokens", 0)) if isinstance(val, dict) else 0

    def add_monthly_token_usage(self, tokens: int) -> int:
        now = datetime.now(tz=timezone.utc)
        key = f"token_usage_{now.year}_{now.month:02d}"
        current = self.get_monthly_token_usage()
        new_total = current + tokens
        self.set_kv(key, {"tokens": new_total, "month": f"{now.year}-{now.month:02d}"})
        return new_total

    # ------------------------------------------------------------------
    # Trade history from fills table
    # ------------------------------------------------------------------

    def load_recent_fills(self, days: int = 30, limit: int = 1000) -> list[dict[str, Any]]:
        """Load fills from the last N days for AI analysis, newest-first up to limit."""
        from src.persistence.models import FillModel, OrderModel
        cutoff = utc_now() - timedelta(days=days)
        with self._store.session() as session:
            rows = session.scalars(
                select(FillModel)
                .where(FillModel.created_at >= cutoff)
                .order_by(FillModel.created_at.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "fill_id": r.fill_id,
                    "order_id": r.order_id,
                    "symbol": r.symbol,
                    "side": r.side,
                    "quantity": r.quantity,
                    "price": r.price,
                    "notional": r.notional,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                }
                for r in rows
            ]

    def load_recent_poly_fills(self, days: int = 30, limit: int = 500) -> list[dict[str, Any]]:
        """Load Polymarket fills from poly_fills table for AI analysis."""
        from src.persistence.models import PolyFillModel
        cutoff = utc_now() - timedelta(days=days)
        with self._store.session() as session:
            rows = session.scalars(
                select(PolyFillModel)
                .where(PolyFillModel.closed_at >= cutoff)
                .order_by(PolyFillModel.closed_at.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "fill_id":  r.fill_id,
                    "symbol":   r.symbol,
                    "side":     r.side,
                    "notional": r.notional,
                    "price":    r.price,
                    "pnl":      r.pnl,
                    "pnl_pct":  r.pnl_pct,
                    "win":      r.win,
                    "strategy": r.strategy,
                    "edge_pct": r.edge_pct,
                    "direction": r.direction,
                    "closed_at": r.closed_at.isoformat() if r.closed_at else None,
                }
                for r in rows
            ]

    def load_positions_summary(self) -> list[dict[str, Any]]:
        """Load current positions with realized P&L for AI context."""
        from src.persistence.models import PositionModel
        with self._store.session() as session:
            rows = session.scalars(select(PositionModel)).all()
            return [
                {
                    "symbol": r.symbol,
                    "quantity": r.quantity,
                    "avg_price": r.avg_price,
                    "realized_pnl": r.realized_pnl,
                    "unrealized_pnl": r.unrealized_pnl,
                }
                for r in rows
            ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proposal_to_dict(row: AIProposalModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "status": row.status,
        "proposal_type": row.proposal_type,
        "current_params": row.current_params,
        "proposed_params": row.proposed_params,
        "reasoning": row.reasoning,
        "trade_count": row.trade_count,
        "win_rate": row.win_rate,
        "avg_pnl_pct": row.avg_pnl_pct,
        "confidence": row.confidence,
        "key_findings": row.key_findings or [],
        "warnings": row.warnings or [],
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
        "applied_by": row.applied_by,
        "rejected_at": row.rejected_at.isoformat() if row.rejected_at else None,
        "auto_apply_after": row.auto_apply_after.isoformat() if row.auto_apply_after else None,
    }


def _log_to_dict(row: AIAnalysisLogModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "analysis_type": row.analysis_type,
        "input_summary": row.input_summary,
        "output_summary": row.output_summary,
        "tokens_used": row.tokens_used,
        "duration_ms": row.duration_ms,
        "model": row.model,
    }
