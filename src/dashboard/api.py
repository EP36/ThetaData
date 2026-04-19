"""FastAPI router — Polymarket + unified dashboard endpoints.

Registered in src/api/app.py via include_router().

GET endpoints are public (no auth).
POST endpoints require the DASHBOARD_API_TOKEN bearer token.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path

from src.dashboard.aggregator import (
    DashboardAggregator,
    pause_poly_bot,
    resume_poly_bot,
)

LOGGER = logging.getLogger("theta.api.poly_dashboard")

_HTML_PATH = Path(__file__).parent.parent / "dashboard" / "index.html"

router = APIRouter()

# Module-level singleton — set by app.py after startup
_aggregator: DashboardAggregator | None = None
_poly_config = None    # PolymarketConfig | None
_poly_client = None    # ClobClient | None
_poly_ledger = None    # PositionsLedger | None

# Tuner singletons
_tuner_params_path: str = os.getenv("POLY_SIGNAL_PARAMS_PATH", "polymarket/signal_params.json")
_tuner_proposal_path: str = "polymarket/signal_params_proposed.json"
_tuner_history_dir: str = "polymarket/signal_params_history"
_tuner_last_run: str = ""
_tuner_last_trade_count: int = 0


def register(aggregator: Any, poly_config: Any, poly_client: Any, poly_ledger: Any) -> None:
    """Wire live infrastructure into the router (called once at app startup)."""
    global _aggregator, _poly_config, _poly_client, _poly_ledger
    _aggregator = aggregator
    _poly_config = poly_config
    _poly_client = poly_client
    _poly_ledger = poly_ledger


# ---------------------------------------------------------------------------
# Auth dependency for POST endpoints
# ---------------------------------------------------------------------------

def _require_dashboard_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    expected = os.getenv("DASHBOARD_API_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="DASHBOARD_API_TOKEN is not configured on the server")
    if authorization is None:
        raise HTTPException(status_code=401, detail="Authorization header required")
    prefix = "bearer "
    raw = authorization.strip()
    if not raw.lower().startswith(prefix):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = raw[len(prefix):].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid dashboard token")


def _ok_response(message: str, **extra: Any) -> dict[str, Any]:
    return {"success": True, "message": message, "timestamp": datetime.now(tz=timezone.utc).isoformat(), **extra}


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Polymarket module not configured (POLY_API_KEY missing)")


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------

@router.get("/", include_in_schema=False)
def get_dashboard_html() -> FileResponse:
    """Serve the single-file vanilla JS dashboard."""
    if not _HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="Dashboard HTML not found")
    return FileResponse(_HTML_PATH, media_type="text/html")


# ---------------------------------------------------------------------------
# GET endpoints — no auth required
# ---------------------------------------------------------------------------

@router.get("/api/snapshot")
def get_snapshot() -> JSONResponse:
    """Full aggregated snapshot (cached 30 s)."""
    if _aggregator is None:
        raise _unavailable()
    return JSONResponse(_aggregator.build_snapshot())


@router.get("/api/positions")
def get_positions() -> JSONResponse:
    """Combined normalized position list from both brokers."""
    if _aggregator is None:
        raise _unavailable()
    snap = _aggregator.build_snapshot()
    combined = snap.get("alpaca_positions", []) + snap.get("poly_positions", [])
    return JSONResponse({"positions": combined, "total": len(combined)})


@router.get("/api/opportunities")
def get_opportunities() -> JSONResponse:
    """Current Polymarket arb opportunities ranked by edge (cached)."""
    if _aggregator is None:
        raise _unavailable()
    snap = _aggregator.build_snapshot()
    return JSONResponse({"opportunities": snap.get("poly_opportunities", [])})


@router.get("/api/alerts")
def get_alerts() -> JSONResponse:
    """Active alerts only."""
    if _aggregator is None:
        raise _unavailable()
    snap = _aggregator.build_snapshot()
    return JSONResponse({"alerts": snap.get("alerts", [])})


# ---------------------------------------------------------------------------
# POST endpoints — require DASHBOARD_API_TOKEN
# ---------------------------------------------------------------------------

@router.post("/api/poly/pause")
def post_poly_pause(
    _: None = None,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """Pause the Polymarket scanner bot."""
    _require_dashboard_token(authorization)
    if _poly_config is None:
        raise _unavailable()
    pause_poly_bot()
    LOGGER.warning("api_poly_pause via dashboard")
    if _aggregator is not None:
        _aggregator.build_snapshot(force=True)
    return _ok_response("Polymarket bot paused")


@router.post("/api/poly/resume")
def post_poly_resume(
    _: None = None,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """Resume the Polymarket scanner bot."""
    _require_dashboard_token(authorization)
    if _poly_config is None:
        raise _unavailable()
    resume_poly_bot()
    LOGGER.info("api_poly_resume via dashboard")
    if _aggregator is not None:
        _aggregator.build_snapshot(force=True)
    return _ok_response("Polymarket bot resumed")


@router.post("/api/poly/scan")
def post_poly_scan(
    _: None = None,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """Trigger an immediate Polymarket scan cycle and return fresh opportunities."""
    _require_dashboard_token(authorization)
    if _poly_config is None or _aggregator is None:
        raise _unavailable()

    from src.polymarket.runner import scan as run_scan

    if _poly_config.dry_run:
        LOGGER.info("api_poly_scan_triggered dry_run=true — scan only, no execution")

    try:
        opps = run_scan(_poly_config)
        _aggregator.update_opportunities(opps)
        _aggregator.build_snapshot(force=True)
        LOGGER.info("api_poly_scan_complete opportunities=%d", len(opps))
        return _ok_response(f"Scan complete — {len(opps)} opportunity(ies) found", opportunities=len(opps))
    except Exception as exc:
        LOGGER.error("api_poly_scan_error error=%s", exc)
        raise HTTPException(status_code=500, detail=f"Scan failed: {exc}") from exc


@router.post("/api/poly/close/{position_id}")
def post_poly_close(
    position_id: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """Manually close an open Polymarket position by ID."""
    _require_dashboard_token(authorization)
    if _poly_config is None or _poly_client is None or _poly_ledger is None:
        raise _unavailable()

    from src.polymarket.monitor import close_position

    positions = _poly_ledger.load()
    match = next((p for p in positions if p.id == position_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"Position {position_id!r} not found")

    from src.polymarket.positions import ACTIVE_STATUSES
    if match.status not in ACTIVE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Position {position_id!r} is already in terminal state: {match.status}",
        )

    if _poly_config.dry_run:
        LOGGER.info(
            "api_poly_close_dry_run id=%s side=%s size_usdc=%.2f — DRY RUN",
            position_id,
            match.side,
            match.size_usdc,
        )

    try:
        ok = close_position(match, _poly_config, _poly_client, _poly_ledger)
        if _aggregator is not None:
            _aggregator.build_snapshot(force=True)
        if ok:
            suffix = " (dry run — no real order placed)" if _poly_config.dry_run else ""
            return _ok_response(f"Position {position_id} close initiated{suffix}")
        raise HTTPException(status_code=500, detail="Close attempt failed — position may still be in closing state")
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error("api_poly_close_error id=%s error=%s", position_id, exc)
        raise HTTPException(status_code=500, detail=f"Close error: {exc}") from exc


# ---------------------------------------------------------------------------
# Tuner endpoints
# ---------------------------------------------------------------------------

@router.get("/api/poly/tuner/status")
def get_tuner_status() -> JSONResponse:
    """Return current tuner status and active signal params."""
    from src.polymarket.tuner import read_proposal
    from src.polymarket.signals import get_signal_params
    proposal = read_proposal(_tuner_proposal_path)
    return JSONResponse({
        "last_run_at": _tuner_last_run,
        "last_trade_count": _tuner_last_trade_count,
        "proposal_pending": proposal is not None,
        "proposal_change_count": (
            len(proposal.get("proposed_changes", [])) if proposal else 0
        ),
        "current_params": get_signal_params(),
    })


@router.get("/api/poly/tuner/proposal")
def get_tuner_proposal() -> JSONResponse:
    """Return the pending tuning proposal, or 404 if none exists."""
    from src.polymarket.tuner import read_proposal
    proposal = read_proposal(_tuner_proposal_path)
    if proposal is None:
        raise HTTPException(status_code=404, detail="No pending proposal")
    return JSONResponse(proposal)


@router.post("/api/poly/tuner/run")
def post_tuner_run(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Any:
    """Trigger a tuning cycle (requires auth). Writes proposal if changes are found."""
    _require_dashboard_token(authorization)
    if _poly_config is None:
        raise _unavailable()

    global _tuner_last_run, _tuner_last_trade_count

    from src.polymarket.feedback import load_feedback_records
    from src.polymarket.tuner import check_minimum_data, propose_tuning, write_proposal

    records = load_feedback_records(
        days=30,
        positions_path=_poly_config.positions_path,
        log_dir=_poly_config.poly_log_dir,
    )
    _tuner_last_trade_count = len(records)
    _tuner_last_run = datetime.now(tz=timezone.utc).isoformat()

    ok, reason = check_minimum_data(records)
    if not ok:
        return _ok_response(
            f"Tuning skipped \u2014 {reason}", skipped=True, reason=reason
        )

    result = propose_tuning(records, days=30, params_path=_tuner_params_path)
    if not result.proposed_changes:
        return _ok_response(
            "Tuning complete \u2014 no adjustments needed",
            changes=0,
            trade_count=result.trade_count,
        )

    write_proposal(result, _tuner_proposal_path)
    return _ok_response(
        f"Tuning proposal written \u2014 {len(result.proposed_changes)} parameter change(s)",
        changes=len(result.proposed_changes),
        trade_count=result.trade_count,
    )


@router.post("/api/poly/tuner/apply")
def post_tuner_apply(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Any:
    """Apply the pending tuning proposal (requires auth)."""
    _require_dashboard_token(authorization)
    from src.polymarket.tuner import read_proposal, apply_proposal
    proposal = read_proposal(_tuner_proposal_path)
    if proposal is None:
        raise HTTPException(status_code=404, detail="No pending proposal to apply")

    change_log = apply_proposal(
        _tuner_proposal_path, _tuner_params_path, _tuner_history_dir
    )
    return _ok_response(
        f"Applied {len(change_log)} parameter change(s)", changes=change_log
    )


@router.post("/api/poly/tuner/reject")
def post_tuner_reject(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Any:
    """Reject and discard the pending tuning proposal (requires auth)."""
    _require_dashboard_token(authorization)
    from src.polymarket.tuner import reject_proposal
    reject_proposal(_tuner_proposal_path)
    return _ok_response("Tuning proposal rejected \u2014 keeping current params")
