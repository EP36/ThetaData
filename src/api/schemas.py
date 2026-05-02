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


class ThetaTradeRecord(BaseModel):
    """Single theta trade log entry from logs/trades.jsonl."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    exchange: str
    asset: str
    quote: str
    side: str
    notional_usd: float
    expected_edge_bps: float
    status: str
    error: Optional[str] = None
    order_id: str = ""
    client_order_id: str = ""


class ThetaStrategyRecord(BaseModel):
    """Per-strategy status derived from trade telemetry."""

    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str
    exchange: str
    enabled: bool
    last_trade_at: Optional[datetime] = None
    last_edge_bps: Optional[float] = None
    last_notional_usd: Optional[float] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    trade_count: int = 0


class ThetaTradeStats(BaseModel):
    """Aggregate counts across all theta trade log entries."""

    model_config = ConfigDict(extra="forbid")

    total: int = 0
    submitted: int = 0
    dry_run: int = 0
    rejected: int = 0
    failed: int = 0
    total_notional_usd: float = 0.0


class ThetaRunnerHeartbeat(BaseModel):
    """Live runner process state from logs/theta_runner_status.json.

    available=False means the heartbeat file has not been written yet —
    the runner has not been started or has never completed a tick.
    stale=True means the file exists but is older than STALE_THRESHOLD_SECONDS.
    """

    model_config = ConfigDict(extra="forbid")

    available: bool
    stale: bool = False
    last_tick_at: Optional[datetime] = None
    mode: Optional[str] = None            # "dry_run" | "live"
    strategies_evaluated: list[str] = Field(default_factory=list)
    iterations_completed: int = 0
    selected_strategy: Optional[str] = None
    last_result: Optional[str] = None     # "no_opportunity" | "dry_run_would_execute" | "executed" | "failed" | "error"
    last_error: Optional[str] = None
    written_at: Optional[datetime] = None


class ThetaRunnerStatusResponse(BaseModel):
    """Theta strategy runner state: live heartbeat + historical trade telemetry."""

    model_config = ConfigDict(extra="forbid")

    runner_status: ThetaRunnerHeartbeat
    strategies: list[ThetaStrategyRecord]
    dry_run: bool                          # derived: heartbeat.mode=="dry_run" when available, else env var
    last_trade_at: Optional[datetime] = None
    total_trade_count: int
    trade_stats: ThetaTradeStats
    recent_trades: list[ThetaTradeRecord]
    fetched_at: datetime


class AuthLoginRequest(BaseModel):
    """Login payload for admin authentication."""

    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class AuthUserResponse(BaseModel):
    """Authenticated user identity returned to clients."""

    model_config = ConfigDict(extra="forbid")

    id: int
    email: str
    role: str
    is_active: bool


class AuthLoginResponse(BaseModel):
    """Session creation response for successful login."""

    model_config = ConfigDict(extra="forbid")

    token: str
    expires_at: datetime
    user: AuthUserResponse


class AuthSessionResponse(BaseModel):
    """Current session metadata response."""

    model_config = ConfigDict(extra="forbid")

    user: AuthUserResponse
    expires_at: datetime


class LogoutResponse(BaseModel):
    """Logout acknowledgement payload."""

    model_config = ConfigDict(extra="forbid")

    ok: bool


class PasswordChangeRequest(BaseModel):
    """Authenticated password-change payload."""

    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: str
    confirm_new_password: str


class PasswordChangeResponse(BaseModel):
    """Password-change acknowledgement payload."""

    model_config = ConfigDict(extra="forbid")

    ok: bool


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
    trailing_stop_pct: Optional[float] = None
    max_position_size: float = 0.25
    max_open_positions: int = 3
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


class RollingMetricPointResponse(BaseModel):
    """Rolling metric point aligned to closed-trade progression."""

    model_config = ConfigDict(extra="forbid")

    trade_index: int
    timestamp: datetime
    win_rate: float
    expectancy: float
    sharpe: float


class RecentWindowMetricsResponse(BaseModel):
    """Recent-trades window summary metrics."""

    model_config = ConfigDict(extra="forbid")

    trades: int
    total_return: float
    win_rate: float
    expectancy: float
    sharpe: float


class StrategyAnalyticsRecordResponse(BaseModel):
    """Strategy-level analytics payload."""

    model_config = ConfigDict(extra="forbid")

    strategy: str
    total_return: float
    win_rate: float
    average_win: float
    average_loss: float
    profit_factor: float
    expectancy: float
    sharpe: float
    max_drawdown: float
    num_trades: int
    average_hold_time_hours: float
    rolling_20_win_rate: float
    rolling_20_expectancy: float
    rolling_20_sharpe: float
    rolling_20_series: list[RollingMetricPointResponse]
    last_5: RecentWindowMetricsResponse
    last_20: RecentWindowMetricsResponse
    last_60: RecentWindowMetricsResponse


class StrategyAnalyticsResponse(BaseModel):
    """Top-level strategy analytics response."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    data_source: Literal["execution", "paper", "backtest"]
    aggregation_scope: Literal["single_run", "multi_run_aggregate"]
    run_count: int
    strategies: list[StrategyAnalyticsRecordResponse]


class StrategyContributionResponse(BaseModel):
    """Per-strategy realized contribution summary."""

    model_config = ConfigDict(extra="forbid")

    strategy: str
    realized_pnl: float
    return_pct: float
    trades: int


class SymbolExposureResponse(BaseModel):
    """Open exposure summary for one symbol."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    quantity: float
    avg_price: float
    notional: float
    unrealized_pnl: float


class OpenRiskSummaryResponse(BaseModel):
    """Portfolio open-risk summary."""

    model_config = ConfigDict(extra="forbid")

    open_positions: int
    gross_exposure: float
    largest_position_notional: float
    cash: float
    day_start_equity: float
    peak_equity: float


class PortfolioAnalyticsResponse(BaseModel):
    """Portfolio-level analytics response."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    data_source: Literal["execution", "paper", "backtest"]
    equity_curve: list[EquityPoint]
    daily_pnl: list[EquityPoint]
    realized_pnl: float
    unrealized_pnl: float
    rolling_drawdown: list[EquityPoint]
    strategy_contribution: list[StrategyContributionResponse]
    exposure_by_symbol: list[SymbolExposureResponse]
    open_risk_summary: OpenRiskSummaryResponse


class ContextBucketPerformanceResponse(BaseModel):
    """Grouped context bucket performance row."""

    model_config = ConfigDict(extra="forbid")

    key: str
    trades: int
    total_return: float
    win_rate: float
    expectancy: float
    sharpe: float
    total_pnl: float


class ContextAnalyticsResponse(BaseModel):
    """Context/regime analytics response."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    data_source: Literal["execution", "paper", "backtest"]
    by_symbol: list[ContextBucketPerformanceResponse]
    by_timeframe: list[ContextBucketPerformanceResponse]
    by_weekday: list[ContextBucketPerformanceResponse]
    by_hour: list[ContextBucketPerformanceResponse]
    by_regime: list[ContextBucketPerformanceResponse]


class StrategyScoreResponse(BaseModel):
    """Selection score and eligibility details for one strategy."""

    model_config = ConfigDict(extra="forbid")

    strategy: str
    signal: float
    eligible: bool
    reasons: list[str]
    score: float
    recent_expectancy: float
    recent_sharpe: float
    win_rate: float
    drawdown_penalty: float
    regime_fit: float
    sizing_multiplier: float


class SelectionStatusResponse(BaseModel):
    """Current deterministic selection/allocation decision payload."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    regime: str
    regime_signals: dict[str, float]
    selected_strategy: Optional[str]
    selected_score: float
    minimum_score_threshold: float
    sizing_multiplier: float
    allocation_fraction: float
    candidates: list[StrategyScoreResponse]


class WorkerSymbolDecisionResponse(BaseModel):
    """Latest worker execution decision for one symbol."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    timeframe: str
    run_id: Optional[str]
    updated_at: Optional[datetime]
    action: str
    order_status: Optional[str]
    selected_strategy: Optional[str]
    active_strategy: Optional[str]
    selected_score: float
    no_trade_reason: Optional[str]
    rejection_reasons: list[str]
    candidates: list[StrategyScoreResponse]


class WorkerExecutionStatusResponse(BaseModel):
    """Worker execution model visibility for universe, locks, and recent decisions."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    worker_name: str
    timeframe: str
    universe_mode: str
    dry_run_enabled: bool
    universe_symbols: list[str]
    scanned_symbols: list[str]
    shortlisted_symbols: list[str]
    allow_multi_strategy_per_symbol: bool
    selected_symbol: Optional[str]
    selected_strategy: Optional[str]
    last_selected_symbol: Optional[str]
    last_selected_strategy: Optional[str]
    last_no_trade_reason: Optional[str]
    symbol_filter_reasons: dict[str, list[str]]
    active_strategy_by_symbol: dict[str, str]
    symbols: list[WorkerSymbolDecisionResponse]


class TradingStatusResponse(BaseModel):
    """Runtime trading-mode status split by signal source and execution venue."""

    model_config = ConfigDict(extra="forbid")

    signal_provider: str = "synthetic"
    trading_venue: str = "alpaca"
    trading_mode: str = "disabled"
    poly_trading_mode: str = "disabled"
    alpaca_trading_mode: str = "disabled"
    poly_dry_run: bool = True
    worker_enable_trading: bool = False
    worker_dry_run: bool = True
    paper_trading_enabled: bool = False
    live_trading_enabled: bool = False
    execution_adapter: str = "alpaca_execution_disabled"
    poly_wallet_address: str = ""


class DashboardSummaryResponse(BaseModel):
    """Top-level dashboard summary data."""

    model_config = ConfigDict(extra="forbid")

    equity: Optional[float]
    daily_pnl: float
    total_pnl: float
    open_positions: int
    system_status: str
    risk_alerts: list[str]
    last_run_id: Optional[str]
    trading_status: TradingStatusResponse = Field(default_factory=TradingStatusResponse)
    equity_breakdown: Optional[dict] = None
    total_deposited: Optional[float] = None


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
    trading_status: TradingStatusResponse = Field(default_factory=TradingStatusResponse)
    worker_heartbeat: Optional[dict[str, Any]]
    recent_runs: list[dict[str, Any]]
    timestamp: datetime
