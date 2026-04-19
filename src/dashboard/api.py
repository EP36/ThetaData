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
