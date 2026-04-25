"""AI insights endpoints — signal params, proposals, analysis log."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

ai_router = APIRouter(prefix="/api/ai", tags=["ai"])

_repo: "AIRepository | None" = None  # type: ignore[name-defined]


def register_ai_repo(repo: "AIRepository") -> None:  # type: ignore[name-defined]
    global _repo
    _repo = repo


def _get_repo() -> "AIRepository":  # type: ignore[name-defined]
    if _repo is None:
        raise HTTPException(status_code=503, detail="AI repository not initialised")
    return _repo


@ai_router.get("/signal-params")
def get_signal_params() -> dict:
    return _get_repo().load_signal_params_full()


@ai_router.get("/proposals")
def get_proposals() -> list:
    return _get_repo().list_proposals(limit=10)


@ai_router.get("/analysis-log")
def get_analysis_log() -> list:
    return _get_repo().list_analysis_log(limit=10)
