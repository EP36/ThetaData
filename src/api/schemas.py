"""Typed request and response schemas for API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class EquityPoint(BaseModel):
    """Single point on an equity- or drawdown-related time series."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    value: float


class TradeRecord(BaseModel):
    """Serialized trade row for API consumers."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    symbol: str
    side: str
    quantity: float
    entry_price: float
    exit_price: float
    realized_pnl: float
    strategy: str
    status: str


class StrategySummary(BaseModel):
    """Visible strategy configuration for UI/API clients."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    status: Literal["enabled", "disabled"]
    parameters: dict[str, Any]


class StrategyUpdateRequest(BaseModel):
    """Mutable strategy configuration payload."""

    model_config = ConfigDict(extra="forbid")

    status: Optional[Literal["enabled", "disabled"]] = None
    parameters: Optional[dict[str, Any]] = None


class BacktestRunRequest(BaseModel):
    """Request payload for launching a backtest run."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = "SPY"
    timeframe: str = "1d"
    start: Optional[str] = None
    end: Optional[str] = None
    strategy: str = "moving_average_crossover"
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    initial_capital: float = 100_000.0
    position_size_pct: float = 1.0
    fixed_fee: float = 1.0
    slippage_pct: float = 0.0005
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    max_position_size: float = 1.0
    max_daily_loss: float = 2_000.0
    force_refresh: bool = False


class BacktestRunResponse(BaseModel):
    """Backtest output payload."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    symbol: str
    timeframe: str
    strategy: str
    metrics: dict[str, float]
    equity_curve: list[EquityPoint]
    drawdown_curve: list[EquityPoint]
    trades: list[TradeRecord]


class DashboardSummaryResponse(BaseModel):
    """Top-level dashboard summary data."""

    model_config = ConfigDict(extra="forbid")

    equity: float
    daily_pnl: float
    total_pnl: float
    open_positions: int
    system_status: str
    risk_alerts: list[str]
    last_run_id: Optional[str]


class RiskStatusResponse(BaseModel):
    """Current operational risk status payload."""

    model_config = ConfigDict(extra="forbid")

    kill_switch_enabled: bool
    current_drawdown: float
    gross_exposure: float
    max_daily_loss: float
    max_position_size: float
    max_open_positions: int
    max_gross_exposure: float
    rejected_orders: list[str]


class TradesResponse(BaseModel):
    """Recent trade records response."""

    model_config = ConfigDict(extra="forbid")

    trades: list[TradeRecord]
    total: int


class KillSwitchRequest(BaseModel):
    """Kill-switch update request."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


class KillSwitchResponse(BaseModel):
    """Kill-switch update response."""

    model_config = ConfigDict(extra="forbid")

    kill_switch_enabled: bool
    updated_at: datetime


class HealthResponse(BaseModel):
    """Basic liveness/readiness response for deployment health checks."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    app_env: str
    database: Literal["ok", "error"]
    paper_trading_enabled: bool
    worker_enable_trading: bool


class ServiceStatusResponse(BaseModel):
    """Operational status response for dashboards and runbooks."""

    model_config = ConfigDict(extra="forbid")

    service_name: str
    app_env: str
    database_ok: bool
    kill_switch_enabled: bool
    paper_trading_enabled: bool
    worker_enable_trading: bool
    worker_heartbeat: Optional[dict[str, Any]]
    recent_runs: list[dict[str, Any]]
    timestamp: datetime
