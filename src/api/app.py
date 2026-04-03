"""FastAPI application exposing trading-system backend endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.api.schemas import (
    BacktestRunRequest,
    BacktestRunResponse,
    ContextAnalyticsResponse,
    DashboardSummaryResponse,
    HealthResponse,
    KillSwitchRequest,
    KillSwitchResponse,
    PortfolioAnalyticsResponse,
    RiskStatusResponse,
    SelectionStatusResponse,
    ServiceStatusResponse,
    StrategyAnalyticsResponse,
    StrategySummary,
    StrategyUpdateRequest,
    TradesResponse,
)
from src.api.services import TradingApiService
from src.config.deployment import DeploymentSettings
from src.persistence import DatabaseStore, PersistenceRepository


def _build_api_service() -> tuple[TradingApiService, DeploymentSettings, PersistenceRepository]:
    """Build deployment-aware API service + dependencies."""
    deployment_settings = DeploymentSettings.from_env()
    repository = PersistenceRepository(
        store=DatabaseStore(database_url=deployment_settings.database_url)
    )
    api_service = TradingApiService(
        cache_dir=Path(deployment_settings.cache_dir),
        trade_log_dir=Path(deployment_settings.log_dir),
        repository=repository,
        deployment_settings=deployment_settings,
    )
    return api_service, deployment_settings, repository

app = FastAPI(
    title="Trading System MVP API",
    version="0.1.0",
    description="Paper-only backend API for research, backtesting, and dashboard consumption.",
)

service, deployment_settings, repository = _build_api_service()
app.state.api_service = service
app.state.deployment_settings = deployment_settings
app.state.repository = repository

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(deployment_settings.cors_allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=[
        "Accept",
        "Authorization",
        "Content-Type",
        "Origin",
        "X-Requested-With",
    ],
)


def _service() -> TradingApiService:
    """Get app-level service instance."""
    return app.state.api_service  # type: ignore[return-value]


def _deployment_settings() -> DeploymentSettings:
    """Get app deployment settings."""
    return app.state.deployment_settings  # type: ignore[return-value]


def _repository() -> PersistenceRepository:
    """Get persistence repository."""
    return app.state.repository  # type: ignore[return-value]


@app.get("/healthz", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Liveness/readiness endpoint for Render health checks."""
    try:
        database_ok = _repository().healthcheck()
    except Exception:
        database_ok = False
    status = "ok" if database_ok else "degraded"
    return HealthResponse(
        status=status,
        app_env=_deployment_settings().app_env,
        database="ok" if database_ok else "error",
        paper_trading_enabled=_deployment_settings().paper_trading_enabled,
        worker_enable_trading=_deployment_settings().worker_enable_trading,
    )


@app.get("/api/system/status", response_model=ServiceStatusResponse)
def get_system_status() -> ServiceStatusResponse:
    """Return deployment/runtime status for operational monitoring."""
    return _service().system_status()


@app.get("/api/dashboard/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary() -> DashboardSummaryResponse:
    """Return top-level dashboard summary values."""
    return _service().dashboard_summary()


@app.post("/api/backtests/run", response_model=BacktestRunResponse)
def post_backtest_run(payload: BacktestRunRequest) -> BacktestRunResponse:
    """Run a backtest and return metrics, curves, and trades."""
    try:
        return _service().run_backtest(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/strategies", response_model=list[StrategySummary])
def get_strategies() -> list[StrategySummary]:
    """List available strategies and current config."""
    return _service().list_strategies()


@app.get("/api/analytics/strategies", response_model=StrategyAnalyticsResponse)
def get_strategy_analytics() -> StrategyAnalyticsResponse:
    """Return strategy-level analytics computed from persisted trading data."""
    return _service().strategy_analytics()


@app.get("/api/analytics/portfolio", response_model=PortfolioAnalyticsResponse)
def get_portfolio_analytics() -> PortfolioAnalyticsResponse:
    """Return portfolio-level analytics computed from persisted trading data."""
    return _service().portfolio_analytics()


@app.get("/api/analytics/context", response_model=ContextAnalyticsResponse)
def get_context_analytics() -> ContextAnalyticsResponse:
    """Return context/regime analytics grouped by symbol/time and regime."""
    return _service().context_analytics()


@app.get("/api/selection/status", response_model=SelectionStatusResponse)
def get_selection_status() -> SelectionStatusResponse:
    """Return latest deterministic selection and allocation decision."""
    return _service().selection_status()


@app.patch("/api/strategies/{name}", response_model=StrategySummary)
def patch_strategy(name: str, payload: StrategyUpdateRequest) -> StrategySummary:
    """Update mutable strategy settings."""
    try:
        return _service().update_strategy(
            name=name,
            status=payload.status,
            parameters=payload.parameters,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/risk/status", response_model=RiskStatusResponse)
def get_risk_status() -> RiskStatusResponse:
    """Return risk-manager-like status payload for the UI."""
    return _service().risk_status()


@app.get("/api/trades", response_model=TradesResponse)
def get_trades() -> TradesResponse:
    """Return recent trade records."""
    return _service().trades()


@app.post("/api/system/kill-switch", response_model=KillSwitchResponse)
def post_kill_switch(payload: KillSwitchRequest) -> KillSwitchResponse:
    """Toggle kill switch state for safety operations."""
    return _service().set_kill_switch(enabled=payload.enabled)
