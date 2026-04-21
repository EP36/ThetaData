"""FastAPI application exposing trading-system backend endpoints."""

from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from src.auth import (
    AuthService,
    AuthenticatedUser,
    AuthenticationError,
    AuthorizationError,
    LoginRateLimitError,
)
from src.auth.bootstrap_admin import maybe_bootstrap_admin_from_settings
from src.api.schemas import (
    AuthLoginRequest,
    AuthLoginResponse,
    AuthSessionResponse,
    AuthUserResponse,
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
    LogoutResponse,
    PasswordChangeRequest,
    PasswordChangeResponse,
    WorkerExecutionStatusResponse,
)
from src.dashboard.api import router as poly_router, register as _poly_register
from src.api.services import TradingApiService
from src.config.deployment import DeploymentSettings
from src.persistence import DatabaseStore, PersistenceRepository

_APP_LOGGER = logging.getLogger("theta.api.app")

AnalyticsSource = Literal["execution", "paper", "backtest"]


def _build_api_service() -> tuple[
    TradingApiService,
    DeploymentSettings,
    PersistenceRepository,
    AuthService,
]:
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
    maybe_bootstrap_admin_from_settings(
        repository=repository,
        settings=deployment_settings,
    )
    auth_service = AuthService(repository=repository, settings=deployment_settings)
    return api_service, deployment_settings, repository, auth_service

app = FastAPI(
    title="Trading System MVP API",
    version="0.1.0",
    description="Paper-only backend API for research, backtesting, and dashboard consumption.",
)

service, deployment_settings, repository, auth_service = _build_api_service()
app.state.api_service = service
app.state.deployment_settings = deployment_settings
app.state.repository = repository
app.state.auth_service = auth_service

app.include_router(poly_router)

# Attempt to initialise the Polymarket dashboard module.
# If POLY_API_KEY / credentials are not set this is a no-op.
try:
    from src.polymarket.config import PolymarketConfig as _PolyConfig
    from src.polymarket.client import ClobClient as _ClobClient
    from src.polymarket.positions import make_ledger as _make_ledger
    from src.dashboard.aggregator import DashboardAggregator as _DashAgg

    _poly_cfg = _PolyConfig.from_env()
    _poly_client = _ClobClient(config=_poly_cfg)
    _poly_ledger = _make_ledger(_poly_cfg.positions_path)
    _poly_agg = _DashAgg(
        poly_config=_poly_cfg,
        ledger=_poly_ledger,
        repository=repository,
    )
    _poly_register(_poly_agg, _poly_cfg, _poly_client, _poly_ledger)
    app.state.poly_aggregator = _poly_agg
    _APP_LOGGER.info(
        "trauto_dashboard_ready dry_run=%s positions_path=%s",
        _poly_cfg.dry_run,
        _poly_cfg.positions_path,
    )
except Exception as _poly_init_exc:
    _APP_LOGGER.warning(
        "trauto_dashboard_poly_unavailable reason=%s — GET / and /api/* poly endpoints will return 503",
        _poly_init_exc,
    )
    app.state.poly_aggregator = None

@app.on_event("startup")
async def _start_ai_background_loop() -> None:
    """Launch the Phase 7 AI analyst background loop as an asyncio task."""
    import asyncio
    db_url = deployment_settings.database_url
    if not db_url:
        _APP_LOGGER.warning("ai_loop_skipped reason=DATABASE_URL_not_set")
        return
    try:
        from trauto.ai.db import AIRepository
        from src.persistence.store import DatabaseStore
        repo = AIRepository(store=DatabaseStore(database_url=db_url))
        repo.ensure_schema()
        repo.seed_signal_params_if_needed()
        from trauto.ai.loop import background_loop
        asyncio.create_task(background_loop(db_url))
        _APP_LOGGER.info("ai_loop_started db_url_set=%s", bool(db_url))
    except Exception as exc:
        _APP_LOGGER.warning("ai_loop_start_failed error=%s — AI features disabled", exc)


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


def _auth_service() -> AuthService:
    """Get auth service instance."""
    return app.state.auth_service  # type: ignore[return-value]


def _extract_bearer_token(authorization: str | None) -> str:
    """Extract bearer token from an Authorization header."""
    if authorization is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    prefix = "bearer "
    header_value = authorization.strip()
    if not header_value.lower().startswith(prefix):
        raise HTTPException(status_code=401, detail="Bearer token is required")
    token = header_value[len(prefix):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is required")
    return token


def _request_ip(request: Request) -> str:
    """Extract best-effort client IP for auth audit and throttling."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        leftmost = forwarded_for.split(",")[0].strip()
        if leftmost:
            return leftmost
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def require_authenticated_session(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> tuple[AuthenticatedUser, datetime]:
    """Resolve current authenticated session from bearer token."""
    token = _extract_bearer_token(authorization)
    try:
        return _auth_service().authenticate_token(token)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def require_authenticated_user(
    session: tuple[AuthenticatedUser, datetime] = Depends(require_authenticated_session),
) -> AuthenticatedUser:
    """Return current authenticated user principal."""
    return session[0]


def require_admin_user(
    user: AuthenticatedUser = Depends(require_authenticated_user),
) -> AuthenticatedUser:
    """Enforce admin-only access for sensitive endpoints."""
    try:
        _auth_service().require_admin(user)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return user


@app.post("/api/auth/login", response_model=AuthLoginResponse)
def post_auth_login(payload: AuthLoginRequest, request: Request) -> AuthLoginResponse:
    """Authenticate an admin user and return a bearer session token."""
    try:
        result = _auth_service().login(
            email=payload.email,
            password=payload.password,
            ip_address=_request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except LoginRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return AuthLoginResponse(
        token=result.token,
        expires_at=result.expires_at,
        user=AuthUserResponse(
            id=result.user.id,
            email=result.user.email,
            role=result.user.role,
            is_active=result.user.is_active,
        ),
    )


@app.get("/api/auth/session", response_model=AuthSessionResponse)
def get_auth_session(
    session: tuple[AuthenticatedUser, datetime] = Depends(require_authenticated_session),
) -> AuthSessionResponse:
    """Return current authenticated user session metadata."""
    user, expires_at = session
    return AuthSessionResponse(
        user=AuthUserResponse(
            id=user.id,
            email=user.email,
            role=user.role,
            is_active=user.is_active,
        ),
        expires_at=expires_at,
    )


@app.post("/api/auth/logout", response_model=LogoutResponse)
def post_auth_logout(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> LogoutResponse:
    """Revoke the current bearer session."""
    token = _extract_bearer_token(authorization)
    _auth_service().logout(token)
    return LogoutResponse(ok=True)


@app.post("/api/auth/password", response_model=PasswordChangeResponse)
def post_auth_password_change(
    payload: PasswordChangeRequest,
    user: AuthenticatedUser = Depends(require_authenticated_user),
) -> PasswordChangeResponse:
    """Allow an authenticated user to rotate account password."""
    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(status_code=422, detail="New password confirmation does not match")
    try:
        _auth_service().change_password(
            user=user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PasswordChangeResponse(ok=True)


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
def get_system_status(
    _user: AuthenticatedUser = Depends(require_authenticated_user),
) -> ServiceStatusResponse:
    """Return deployment/runtime status for operational monitoring."""
    return _service().system_status()


@app.get("/api/dashboard/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    _user: AuthenticatedUser = Depends(require_authenticated_user),
) -> DashboardSummaryResponse:
    """Return top-level dashboard summary values."""
    return _service().dashboard_summary()


@app.post("/api/backtests/run", response_model=BacktestRunResponse)
def post_backtest_run(
    payload: BacktestRunRequest,
    admin_user: AuthenticatedUser = Depends(require_admin_user),
) -> BacktestRunResponse:
    """Run a backtest and return metrics, curves, and trades."""
    try:
        return _service().run_backtest(
            request=payload,
            actor_user_id=admin_user.id,
            actor_email=admin_user.email,
            actor_role=admin_user.role,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/strategies", response_model=list[StrategySummary])
def get_strategies(
    _user: AuthenticatedUser = Depends(require_authenticated_user),
) -> list[StrategySummary]:
    """List available strategies and current config."""
    return _service().list_strategies()


@app.get("/api/analytics/strategies", response_model=StrategyAnalyticsResponse)
def get_strategy_analytics(
    source: AnalyticsSource = Query(default="execution"),
    _user: AuthenticatedUser = Depends(require_authenticated_user),
) -> StrategyAnalyticsResponse:
    """Return strategy-level analytics computed from persisted trading data."""
    return _service().strategy_analytics(source=source)


@app.get("/api/analytics/portfolio", response_model=PortfolioAnalyticsResponse)
def get_portfolio_analytics(
    source: AnalyticsSource = Query(default="execution"),
    _user: AuthenticatedUser = Depends(require_authenticated_user),
) -> PortfolioAnalyticsResponse:
    """Return portfolio-level analytics computed from persisted trading data."""
    return _service().portfolio_analytics(source=source)


@app.get("/api/analytics/context", response_model=ContextAnalyticsResponse)
def get_context_analytics(
    source: AnalyticsSource = Query(default="execution"),
    _user: AuthenticatedUser = Depends(require_authenticated_user),
) -> ContextAnalyticsResponse:
    """Return context/regime analytics grouped by symbol/time and regime."""
    return _service().context_analytics(source=source)


@app.get("/api/selection/status", response_model=SelectionStatusResponse)
def get_selection_status(
    _user: AuthenticatedUser = Depends(require_authenticated_user),
) -> SelectionStatusResponse:
    """Return latest deterministic selection and allocation decision."""
    return _service().selection_status()


@app.get("/api/worker/execution-status", response_model=WorkerExecutionStatusResponse)
def get_worker_execution_status(
    _user: AuthenticatedUser = Depends(require_authenticated_user),
) -> WorkerExecutionStatusResponse:
    """Return worker universe, active strategy locks, and latest per-symbol decisions."""
    return _service().worker_execution_status()


@app.patch("/api/strategies/{name}", response_model=StrategySummary)
def patch_strategy(
    name: str,
    payload: StrategyUpdateRequest,
    admin_user: AuthenticatedUser = Depends(require_admin_user),
) -> StrategySummary:
    """Update mutable strategy settings."""
    try:
        return _service().update_strategy(
            name=name,
            status=payload.status,
            parameters=payload.parameters,
            actor_user_id=admin_user.id,
            actor_email=admin_user.email,
            actor_role=admin_user.role,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/risk/status", response_model=RiskStatusResponse)
def get_risk_status(
    _user: AuthenticatedUser = Depends(require_authenticated_user),
) -> RiskStatusResponse:
    """Return risk-manager-like status payload for the UI."""
    return _service().risk_status()


@app.get("/api/trades", response_model=TradesResponse)
def get_trades(
    _user: AuthenticatedUser = Depends(require_authenticated_user),
) -> TradesResponse:
    """Return recent trade records."""
    return _service().trades()


@app.post("/api/system/kill-switch", response_model=KillSwitchResponse)
def post_kill_switch(
    payload: KillSwitchRequest,
    admin_user: AuthenticatedUser = Depends(require_admin_user),
) -> KillSwitchResponse:
    """Toggle kill switch state for safety operations."""
    return _service().set_kill_switch(
        enabled=payload.enabled,
        actor_user_id=admin_user.id,
        actor_email=admin_user.email,
        actor_role=admin_user.role,
    )
