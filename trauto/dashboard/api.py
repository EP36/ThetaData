"""New engine and strategy API endpoints for the trauto platform.

These extend the existing dashboard router (src/dashboard/api.py) with
new endpoints for the core engine, strategy management, and backtester.

Mount this router alongside the existing poly_router in src/api/app.py:
    from trauto.dashboard.api import router as engine_router
    app.include_router(engine_router)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

LOGGER = logging.getLogger("trauto.dashboard.api")

router = APIRouter()

# Module-level engine singleton — set by the app on startup
_engine: "TradingEngine | None" = None
_backtester: "BacktestRunner | None" = None


def register_engine(engine: "TradingEngine", backtester: "BacktestRunner | None" = None) -> None:
    """Wire the running engine into the router (called once at app startup)."""
    global _engine, _backtester
    _engine = engine
    _backtester = backtester


# ---------------------------------------------------------------------------
# Auth helper (same pattern as existing dashboard API)
# ---------------------------------------------------------------------------

def _require_token(authorization: str | None = Header(default=None, alias="Authorization")) -> None:
    expected = os.getenv("DASHBOARD_API_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="DASHBOARD_API_TOKEN not configured")
    if authorization is None:
        raise HTTPException(status_code=401, detail="Authorization header required")
    raw = authorization.strip()
    if not raw.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = raw[7:].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid token")


def _ok(message: str, **extra: Any) -> dict[str, Any]:
    return {"success": True, "message": message,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(), **extra}


def _need_engine() -> "TradingEngine":
    if _engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    return _engine


# ---------------------------------------------------------------------------
# Engine endpoints
# ---------------------------------------------------------------------------

@router.get("/api/engine/status")
def get_engine_status() -> dict[str, Any]:
    """Return engine runtime stats: tick rate, uptime, strategies loaded."""
    engine = _need_engine()
    stats = engine.get_stats()
    return {
        "tick_rate_hz": stats.tick_rate_hz,
        "tick_count": stats.tick_count,
        "uptime_sec": stats.uptime_sec,
        "started_at": stats.started_at,
        "strategies_loaded": stats.strategies_loaded,
        "strategies_enabled": stats.strategies_enabled,
        "emergency_stop": stats.emergency_stop,
        "portfolio": engine.portfolio.to_dict(),
        "circuit_breakers": engine.risk_manager.circuit_breaker_status(),
    }


@router.post("/api/engine/start")
async def post_engine_start(
    _: None = None,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """Clear emergency stop and allow execution to resume."""
    _require_token(authorization)
    engine = _need_engine()
    await engine.resume()
    return _ok("Emergency stop cleared — engine resumed")


@router.post("/api/engine/stop")
async def post_engine_stop(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """Activate emergency stop — halts all new order execution immediately."""
    _require_token(authorization)
    engine = _need_engine()
    await engine.stop(emergency=True)
    return _ok("Emergency stop activated — all execution halted")


# ---------------------------------------------------------------------------
# Circuit breaker management
# ---------------------------------------------------------------------------

@router.post("/api/engine/circuit-breaker/{broker}/resume")
def post_circuit_breaker_resume(
    broker: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """Manually resume a tripped circuit breaker for a broker."""
    _require_token(authorization)
    engine = _need_engine()
    engine.risk_manager.manual_resume_circuit_breaker(broker)
    return _ok(f"Circuit breaker manually resumed for broker={broker}")


# ---------------------------------------------------------------------------
# Strategy endpoints
# ---------------------------------------------------------------------------

@router.get("/api/strategies")
def get_strategies() -> list[dict[str, Any]]:
    """Return all loaded strategies with current status and config."""
    engine = _need_engine()
    return engine.get_strategy_statuses()


@router.get("/api/strategies/{name}")
def get_strategy(name: str) -> dict[str, Any]:
    """Return status for a single strategy."""
    engine = _need_engine()
    statuses = engine.get_strategy_statuses()
    for s in statuses:
        if s["name"] == name:
            return s
    raise HTTPException(status_code=404, detail=f"Strategy not found: {name}")


class StrategyConfigUpdate(BaseModel):
    enabled: bool | None = None
    dry_run: bool | None = None
    capital_allocation_pct: float | None = None
    max_positions: int | None = None
    schedule: str | None = None


@router.post("/api/strategies/{name}/enable")
def post_strategy_enable(
    name: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    _require_token(authorization)
    engine = _need_engine()
    try:
        engine.update_strategy(name, {"enabled": True})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _ok(f"Strategy {name} enabled")


@router.post("/api/strategies/{name}/disable")
def post_strategy_disable(
    name: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    _require_token(authorization)
    engine = _need_engine()
    try:
        engine.update_strategy(name, {"enabled": False})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _ok(f"Strategy {name} disabled")


@router.put("/api/strategies/{name}/config")
def put_strategy_config(
    name: str,
    payload: StrategyConfigUpdate,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """Update strategy allocation, schedule, and risk params live."""
    _require_token(authorization)
    engine = _need_engine()
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=422, detail="No updates provided")
    try:
        engine.update_strategy(name, updates)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _ok(f"Strategy {name} config updated", updates=updates)


# ---------------------------------------------------------------------------
# Backtester endpoints
# ---------------------------------------------------------------------------

class BacktestRequest(BaseModel):
    strategy_name: str
    start_date: str
    end_date: str
    symbol: str = "SPY"
    initial_capital: float = 100_000.0
    poly_history_path: str = ""
    use_live_params: bool = True


@router.post("/api/backtest/run")
def post_backtest_run(
    payload: BacktestRequest,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """Submit a backtest job (async). Returns job_id to poll."""
    _require_token(authorization)
    if _backtester is None:
        raise HTTPException(status_code=503, detail="Backtester not initialized")
    job_id = _backtester.submit(
        strategy_name=payload.strategy_name,
        start_date=payload.start_date,
        end_date=payload.end_date,
        symbol=payload.symbol,
        initial_capital=payload.initial_capital,
        poly_history_path=payload.poly_history_path,
        use_live_params=payload.use_live_params,
    )
    return _ok("Backtest submitted", job_id=job_id)


@router.get("/api/backtest/status/{job_id}")
def get_backtest_status(job_id: str) -> dict[str, Any]:
    """Return job status: pending / running / complete / failed."""
    if _backtester is None:
        raise HTTPException(status_code=503, detail="Backtester not initialized")
    job = _backtester.get_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return {
        "job_id": job.job_id,
        "strategy_name": job.strategy_name,
        "status": job.status.value,
        "submitted_at": job.submitted_at,
        "completed_at": job.completed_at,
        "error": job.error,
        "result_path": job.result_path,
    }


@router.get("/api/backtest/results/{job_id}")
def get_backtest_results(job_id: str) -> dict[str, Any]:
    """Return full results for a completed backtest job."""
    if _backtester is None:
        raise HTTPException(status_code=503, detail="Backtester not initialized")
    # Try in-memory first
    result = _backtester.get_result(job_id)
    if result is not None:
        from dataclasses import asdict
        return asdict(result)
    # Fall back to disk
    from trauto.backtester.report import read_result
    disk_result = read_result(job_id)
    if disk_result is None:
        raise HTTPException(status_code=404, detail=f"Result not found: {job_id}")
    return disk_result


@router.get("/api/backtest/list")
def get_backtest_list() -> list[dict[str, Any]]:
    """Return summary list of all past backtest runs."""
    from trauto.backtester.report import list_results
    return list_results()
