"""Service layer for API handlers."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, field
import logging
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import numpy as np
import pandas as pd

from src.config.deployment import DeploymentSettings
from src.api.schemas import (
    BacktestRunRequest,
    BacktestRunResponse,
    ContextAnalyticsResponse,
    ContextBucketPerformanceResponse,
    DashboardSummaryResponse,
    EquityPoint,
    KillSwitchResponse,
    OpenRiskSummaryResponse,
    PortfolioAnalyticsResponse,
    RiskStatusResponse,
    RollingMetricPointResponse,
    RecentWindowMetricsResponse,
    SelectionStatusResponse,
    ServiceStatusResponse,
    StrategyAnalyticsRecordResponse,
    StrategyAnalyticsResponse,
    StrategyContributionResponse,
    StrategyScoreResponse,
    StrategySummary,
    SymbolExposureResponse,
    TradeRecord,
    TradesResponse,
)
from src.analytics.performance_layer import (
    ContextBucketPerformance,
    PerformanceAnalyticsSnapshot,
    StrategyAnalytics,
    build_performance_snapshot,
    empty_snapshot,
)
from src.backtest.engine import BacktestResult
from src.cli.services import run_backtest as run_backtest_workflow
from src.execution.models import Fill
from src.observability import clear_run, configure_logging, start_run
from src.persistence import PersistenceRepository
from src.strategies import get_strategy_class, list_strategies

LOGGER = logging.getLogger("theta.api.services")
RISK_PER_TRADE_PCT = 0.01
MAX_POSITION_SIZE_CAP_PCT = 0.25
MAX_OPEN_POSITIONS_CAP = 3


def _drawdown_series(equity_curve: pd.Series) -> pd.Series:
    """Compute drawdown series from equity."""
    if equity_curve.empty:
        return pd.Series(dtype=float)
    running_peak = equity_curve.cummax()
    return (equity_curve / running_peak - 1.0).fillna(0.0)


def _series_to_points(series: pd.Series) -> list[EquityPoint]:
    """Convert a datetime-indexed Series to API point objects."""
    if series.empty:
        return []
    points: list[EquityPoint] = []
    for timestamp, value in series.items():
        points.append(
            EquityPoint(
                timestamp=pd.Timestamp(timestamp).to_pydatetime(),
                value=float(value),
            )
        )
    return points


def _strategy_defaults(strategy_name: str) -> dict[str, Any]:
    """Extract dataclass field defaults from a registered strategy class."""
    strategy_cls = get_strategy_class(strategy_name)
    dataclass_fields = getattr(strategy_cls, "__dataclass_fields__", {})
    defaults: dict[str, Any] = {}
    for name, field_info in dataclass_fields.items():
        if name in {"name", "required_columns"}:
            continue
        if not field_info.init:
            continue
        if field_info.default is not MISSING:
            defaults[name] = field_info.default
            continue
        if field_info.default_factory is not MISSING:
            defaults[name] = field_info.default_factory()
    return defaults


def _optional_float(value: Any) -> float | None:
    """Best-effort conversion to optional float."""
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(parsed):
        return None
    return float(parsed)


def _to_trade_records(
    result: BacktestResult,
    symbol: str,
    strategy_name: str,
) -> list[TradeRecord]:
    """Convert backtest trades into UI-friendly records."""
    trade_records: list[TradeRecord] = []
    entry_price = 0.0

    for trade in result.trades:
        timestamp = pd.Timestamp(trade.timestamp).to_pydatetime()
        side = str(trade.side).upper()
        if side == "BUY":
            entry_price = float(trade.fill_price)

        realized_pnl = 0.0
        exit_price = float(trade.fill_price)
        if side == "SELL":
            realized_pnl = float((exit_price - entry_price) * trade.quantity - trade.fee)

        trade_records.append(
            TradeRecord(
                timestamp=timestamp,
                symbol=symbol,
                side=side,
                quantity=float(trade.quantity),
                entry_price=float(entry_price if side == "SELL" else trade.fill_price),
                exit_price=exit_price,
                realized_pnl=realized_pnl,
                strategy=strategy_name,
                status="filled",
            )
        )
    return trade_records


def _window_to_response(window: Any) -> RecentWindowMetricsResponse:
    """Convert analytics window dataclass to API schema."""
    return RecentWindowMetricsResponse(
        trades=int(window.trades),
        total_return=float(window.total_return),
        win_rate=float(window.win_rate),
        expectancy=float(window.expectancy),
        sharpe=float(window.sharpe),
    )


def _strategy_analytics_to_response(item: StrategyAnalytics) -> StrategyAnalyticsRecordResponse:
    """Convert strategy analytics dataclass to API schema."""
    return StrategyAnalyticsRecordResponse(
        strategy=item.strategy,
        total_return=float(item.total_return),
        win_rate=float(item.win_rate),
        average_win=float(item.average_win),
        average_loss=float(item.average_loss),
        profit_factor=float(item.profit_factor),
        expectancy=float(item.expectancy),
        sharpe=float(item.sharpe),
        max_drawdown=float(item.max_drawdown),
        num_trades=int(item.num_trades),
        average_hold_time_hours=float(item.average_hold_time_hours),
        rolling_20_win_rate=float(item.rolling_20_win_rate),
        rolling_20_expectancy=float(item.rolling_20_expectancy),
        rolling_20_sharpe=float(item.rolling_20_sharpe),
        rolling_20_series=[
            RollingMetricPointResponse(
                trade_index=int(point.trade_index),
                timestamp=pd.Timestamp(point.timestamp).to_pydatetime(),
                win_rate=float(point.win_rate),
                expectancy=float(point.expectancy),
                sharpe=float(point.sharpe),
            )
            for point in item.rolling_20_series
        ],
        last_5=_window_to_response(item.last_5),
        last_20=_window_to_response(item.last_20),
        last_60=_window_to_response(item.last_60),
    )


def _context_bucket_to_response(item: ContextBucketPerformance) -> ContextBucketPerformanceResponse:
    """Convert context bucket analytics dataclass to API schema."""
    return ContextBucketPerformanceResponse(
        key=item.key,
        trades=int(item.trades),
        total_return=float(item.total_return),
        win_rate=float(item.win_rate),
        expectancy=float(item.expectancy),
        sharpe=float(item.sharpe),
        total_pnl=float(item.total_pnl),
    )


@dataclass(slots=True)
class StrategyState:
    """Mutable runtime state for one strategy."""

    description: str
    status: Literal["enabled", "disabled"] = "enabled"
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TradingApiService:
    """High-level API operations composed from backend modules."""

    cache_dir: Path = Path("data/cache")
    trade_log_dir: Path = Path("logs")
    repository: PersistenceRepository | None = None
    deployment_settings: DeploymentSettings | None = None
    kill_switch_enabled: bool = False
    rejected_orders: list[str] = field(default_factory=list)
    last_run_id: str | None = None
    last_backtest: BacktestResult | None = None
    last_backtest_symbol: str = "SPY"
    last_backtest_strategy: str = "moving_average_crossover"
    last_risk_config: dict[str, float] = field(
        default_factory=lambda: {
            "max_daily_loss": 2_000.0,
            "max_position_size": 0.25,
            "max_open_positions": 3.0,
            "max_gross_exposure": 1.0,
        }
    )
    strategy_state: dict[str, StrategyState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Bootstrap strategy state from registry."""
        configure_logging(log_dir=self._log_dir())
        if self.repository is not None:
            self.repository.initialize(
                starting_cash=self._initial_capital_for_bootstrap()
            )
            self.kill_switch_enabled = self.repository.get_global_kill_switch()
        self._initialize_strategy_state(use_persisted=True)

    def reset(self) -> None:
        """Reset mutable state for test isolation."""
        self.kill_switch_enabled = False
        if self.repository is not None:
            self.repository.set_global_kill_switch(False, reason="reset")
        self.rejected_orders.clear()
        self.last_run_id = None
        self.last_backtest = None
        self.last_backtest_symbol = "SPY"
        self.last_backtest_strategy = "moving_average_crossover"
        self.last_risk_config = {
            "max_daily_loss": 2_000.0,
            "max_position_size": 0.25,
            "max_open_positions": 3.0,
            "max_gross_exposure": 1.0,
        }
        self._initialize_strategy_state(use_persisted=False)

    def _initial_capital_for_bootstrap(self) -> float:
        """Return configured initial capital for repository bootstrap."""
        if self.deployment_settings is not None:
            return float(self.deployment_settings.initial_capital)
        return 100_000.0

    def _log_dir(self) -> str:
        """Resolve configured log directory."""
        if self.deployment_settings is not None:
            return self.deployment_settings.log_dir
        return "logs"

    def _performance_snapshot(self) -> PerformanceAnalyticsSnapshot:
        """Build analytics snapshot from persisted runtime state when available."""
        starting_equity = self._initial_capital_for_bootstrap()
        if self.repository is None:
            from src.persistence.repository import PortfolioSnapshot

            if self.last_backtest is None:
                empty = PortfolioSnapshot(
                    cash=starting_equity,
                    day_start_equity=starting_equity,
                    peak_equity=starting_equity,
                    positions={},
                )
                return empty_snapshot(empty, starting_equity=starting_equity)

            fills: list[dict[str, Any]] = []
            for trade in self.last_backtest.trades:
                fills.append(
                    {
                        "run_id": self.last_run_id or "in_memory_run",
                        "timestamp": pd.Timestamp(trade.timestamp),
                        "symbol": self.last_backtest_symbol,
                        "side": str(trade.side).upper(),
                        "quantity": float(trade.quantity),
                        "price": float(trade.fill_price),
                        "strategy": self.last_backtest_strategy,
                    }
                )
            last_equity = (
                float(self.last_backtest.equity_curve.iloc[-1])
                if not self.last_backtest.equity_curve.empty
                else starting_equity
            )
            portfolio = PortfolioSnapshot(
                cash=last_equity,
                day_start_equity=starting_equity,
                peak_equity=max(last_equity, starting_equity),
                positions={},
            )
            runs = [
                {
                    "run_id": self.last_run_id or "in_memory_run",
                    "strategy": self.last_backtest_strategy,
                    "timeframe": "unknown",
                    "details": {},
                }
            ]
            return build_performance_snapshot(
                fills=fills,
                runs=runs,
                portfolio_snapshot=portfolio,
                starting_equity=starting_equity,
            )

        snapshot = self.repository.load_portfolio_snapshot(default_cash=starting_equity)
        fills = self.repository.recent_fills(limit=5000)
        runs = self.repository.recent_runs(limit=2000)
        return build_performance_snapshot(
            fills=fills,
            runs=runs,
            portfolio_snapshot=snapshot,
            starting_equity=starting_equity,
        )

    def _initialize_strategy_state(self, use_persisted: bool) -> None:
        """Initialize or reset strategy state from the strategy registry."""
        self.strategy_state.clear()
        persisted_configs: dict[str, dict[str, Any]] = {}
        if self.repository is not None and use_persisted:
            persisted_configs = self.repository.load_strategy_configs()
        for strategy_name in list_strategies():
            strategy_cls = get_strategy_class(strategy_name)
            description = (strategy_cls.__doc__ or "").strip().splitlines()[0] or strategy_name
            defaults = _strategy_defaults(strategy_name)
            persisted = persisted_configs.get(strategy_name, {})
            status = str(persisted.get("status", "enabled"))
            parameters = defaults
            persisted_parameters = persisted.get("parameters")
            if isinstance(persisted_parameters, dict):
                merged = dict(defaults)
                merged.update(persisted_parameters)
                try:
                    strategy_cls(**merged)
                    parameters = merged
                except (TypeError, ValueError):
                    parameters = defaults
            self.strategy_state[strategy_name] = StrategyState(
                description=description,
                status=status if status in {"enabled", "disabled"} else "enabled",
                parameters=parameters,
            )
            if self.repository is not None:
                self.repository.upsert_strategy_config(
                    name=strategy_name,
                    status=self.strategy_state[strategy_name].status,
                    parameters=dict(self.strategy_state[strategy_name].parameters),
                )

    def list_strategies(self) -> list[StrategySummary]:
        """Return registered strategy configurations."""
        return [
            StrategySummary(
                name=name,
                description=state.description,
                status=state.status,
                parameters=dict(state.parameters),
            )
            for name, state in sorted(self.strategy_state.items())
        ]

    def update_strategy(
        self,
        name: str,
        status: Literal["enabled", "disabled"] | None,
        parameters: dict[str, Any] | None,
    ) -> StrategySummary:
        """Update strategy status and/or default parameters."""
        if name not in self.strategy_state:
            raise KeyError(f"Unknown strategy '{name}'")

        state = self.strategy_state[name]
        if status is not None:
            state.status = status
        if parameters:
            merged = dict(state.parameters)
            merged.update(parameters)
            strategy_cls = get_strategy_class(name)
            try:
                strategy_cls(**merged)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid parameters for strategy '{name}': {exc}"
                ) from exc
            state.parameters = merged
        if self.repository is not None:
            self.repository.upsert_strategy_config(
                name=name,
                status=state.status,
                parameters=dict(state.parameters),
            )

        return StrategySummary(
            name=name,
            description=state.description,
            status=state.status,
            parameters=dict(state.parameters),
        )

    def run_backtest(self, request: BacktestRunRequest) -> BacktestRunResponse:
        """Run a backtest using existing backtest modules."""
        if request.strategy not in self.strategy_state:
            raise KeyError(f"Unknown strategy '{request.strategy}'")
        if self.kill_switch_enabled:
            self.rejected_orders.append("backtest_run_rejected_kill_switch_enabled")
            raise PermissionError("Kill switch is enabled")

        strategy_state = self.strategy_state[request.strategy]
        if strategy_state.status != "enabled":
            raise PermissionError(f"Strategy '{request.strategy}' is disabled")

        strategy_params = dict(strategy_state.parameters)
        strategy_params.update(request.strategy_params)

        strategy_stop_loss = _optional_float(strategy_params.get("stop_loss_pct"))
        strategy_take_profit = _optional_float(strategy_params.get("take_profit_pct"))
        strategy_trailing_stop = _optional_float(strategy_params.get("trailing_stop_pct"))

        effective_stop_loss_pct = (
            float(request.stop_loss_pct)
            if request.stop_loss_pct is not None
            else strategy_stop_loss
        )
        effective_take_profit_pct = (
            float(request.take_profit_pct)
            if request.take_profit_pct is not None
            else strategy_take_profit
        )
        effective_trailing_stop_pct = (
            float(request.trailing_stop_pct)
            if request.trailing_stop_pct is not None
            else strategy_trailing_stop
        )

        effective_max_position_size = float(
            min(MAX_POSITION_SIZE_CAP_PCT, request.max_position_size)
        )
        effective_max_open_positions = int(min(MAX_OPEN_POSITIONS_CAP, request.max_open_positions))
        risk_per_trade_amount = float(request.initial_capital * RISK_PER_TRADE_PCT)
        if effective_stop_loss_pct is not None and effective_stop_loss_pct > 0:
            raw_position_size_pct = float(RISK_PER_TRADE_PCT / effective_stop_loss_pct)
        else:
            raw_position_size_pct = float(request.position_size_pct)
        effective_position_size_pct = float(
            min(raw_position_size_pct, effective_max_position_size)
        )

        run_id = uuid4().hex
        configure_logging(log_dir=self._log_dir())
        start_run(run_id=run_id)
        if self.repository is not None:
            self.repository.start_run(
                run_id=run_id,
                service="api",
                symbol=request.symbol,
                timeframe=request.timeframe,
                strategy=request.strategy,
                details={"source": "api_backtest"},
            )
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="api_backtest_requested",
                run_id=run_id,
                payload={
                    "symbol": request.symbol,
                    "timeframe": request.timeframe,
                    "strategy": request.strategy,
                },
            )
        LOGGER.info(
            "api_backtest_requested run_id=%s symbol=%s timeframe=%s strategy=%s",
            run_id,
            request.symbol,
            request.timeframe,
            request.strategy,
        )
        LOGGER.info(
            "position_size_calculated run_id=%s symbol=%s risk_per_trade_pct=%.4f risk_per_trade=%.2f stop_loss_pct=%s raw_position_size_pct=%.6f capped_position_size_pct=%.6f max_open_positions=%d",
            run_id,
            request.symbol,
            RISK_PER_TRADE_PCT,
            risk_per_trade_amount,
            f"{effective_stop_loss_pct:.6f}" if effective_stop_loss_pct is not None else "none",
            raw_position_size_pct,
            effective_position_size_pct,
            effective_max_open_positions,
        )
        trade_log_path = (
            self.trade_log_dir / f"{request.symbol}_{request.strategy}_api_trades.csv"
        )
        try:
            result = run_backtest_workflow(
                symbol=request.symbol,
                timeframe=request.timeframe,
                strategy_name=request.strategy,
                strategy_params=strategy_params,
                start=request.start,
                end=request.end,
                cache_dir=self.cache_dir,
                trade_log_path=trade_log_path,
                initial_capital=request.initial_capital,
                position_size_pct=effective_position_size_pct,
                fixed_fee=request.fixed_fee,
                slippage_pct=request.slippage_pct,
                stop_loss_pct=effective_stop_loss_pct,
                take_profit_pct=effective_take_profit_pct,
                trailing_stop_pct=effective_trailing_stop_pct,
                max_position_size=effective_max_position_size,
                max_open_positions=effective_max_open_positions,
                max_daily_loss=request.max_daily_loss,
                force_refresh=request.force_refresh,
                run_id=run_id,
            )

            self.last_run_id = run_id
            self.last_backtest = result
            self.last_backtest_symbol = request.symbol
            self.last_backtest_strategy = request.strategy
            self.last_risk_config = {
                "max_daily_loss": float(request.max_daily_loss),
                "max_position_size": float(effective_max_position_size),
                "max_open_positions": float(effective_max_open_positions),
                "max_gross_exposure": float(1.0),
            }

            drawdown = _drawdown_series(result.equity_curve)
            trade_records = _to_trade_records(
                result=result,
                symbol=request.symbol,
                strategy_name=request.strategy,
            )
            LOGGER.info(
                "api_backtest_completed run_id=%s symbol=%s trades=%d",
                run_id,
                request.symbol,
                len(trade_records),
            )
            if self.repository is not None:
                for index, trade in enumerate(result.trades):
                    timestamp = pd.Timestamp(trade.timestamp)
                    self.repository.record_fill(
                        fill=Fill(
                            order_id=f"{run_id}-bt-{index}",
                            symbol=request.symbol,
                            side=str(trade.side).upper(),
                            quantity=float(trade.quantity),
                            price=float(trade.fill_price),
                            timestamp=timestamp,
                            notional=float(trade.quantity * trade.fill_price),
                        ),
                        run_id=run_id,
                    )
                self.repository.finish_run(
                    run_id=run_id,
                    status="completed",
                    details={
                        "trades": len(trade_records),
                        "metrics": {key: float(value) for key, value in result.metrics.items()},
                    },
                )
                self.repository.append_log_event(
                    level="INFO",
                    logger_name=LOGGER.name,
                    event="api_backtest_completed",
                    run_id=run_id,
                    payload={
                        "symbol": request.symbol,
                        "strategy": request.strategy,
                        "trades": len(trade_records),
                    },
                )
            return BacktestRunResponse(
                run_id=run_id,
                symbol=request.symbol,
                timeframe=request.timeframe,
                strategy=request.strategy,
                metrics={
                    **{key: float(value) for key, value in result.metrics.items()},
                    "risk_per_trade_pct": float(RISK_PER_TRADE_PCT),
                    "risk_per_trade": float(risk_per_trade_amount),
                    "position_size_pct": float(effective_position_size_pct),
                    "stop_loss_pct_used": (
                        float(effective_stop_loss_pct) if effective_stop_loss_pct is not None else 0.0
                    ),
                    "max_position_size_pct": float(effective_max_position_size),
                    "max_open_positions": float(effective_max_open_positions),
                },
                equity_curve=_series_to_points(result.equity_curve),
                drawdown_curve=_series_to_points(drawdown),
                trades=trade_records,
            )
        except Exception as exc:
            if self.repository is not None:
                self.repository.finish_run(
                    run_id=run_id,
                    status="failed",
                    error_message=str(exc),
                )
                self.repository.append_log_event(
                    level="ERROR",
                    logger_name=LOGGER.name,
                    event="api_backtest_failed",
                    run_id=run_id,
                    payload={"error": str(exc)},
                )
            raise
        finally:
            clear_run()

    def dashboard_summary(self) -> DashboardSummaryResponse:
        """Return current dashboard summary from persisted paper state when available."""
        if self.repository is not None:
            self.kill_switch_enabled = self.repository.get_global_kill_switch()

            snapshot = self.repository.load_portfolio_snapshot(
                default_cash=self._initial_capital_for_bootstrap()
            )
            open_positions = sum(
                1 for position in snapshot.positions.values() if float(position.quantity) > 0.0
            )
            position_value = sum(
                (float(position.quantity) * float(position.avg_price)) + float(position.unrealized_pnl)
                for position in snapshot.positions.values()
            )
            equity = float(snapshot.cash + position_value)
            daily_pnl = float(equity - snapshot.day_start_equity)
            total_pnl = float(equity - self._initial_capital_for_bootstrap())
            alerts = ["kill_switch_enabled"] if self.kill_switch_enabled else []

            last_run_id = self.last_run_id
            if last_run_id is None:
                recent_runs = self.repository.recent_runs(limit=1)
                if recent_runs:
                    last_run_id = str(recent_runs[0].get("run_id") or "")
                    if not last_run_id:
                        last_run_id = None

            return DashboardSummaryResponse(
                equity=equity,
                daily_pnl=daily_pnl,
                total_pnl=total_pnl,
                open_positions=int(open_positions),
                system_status=(
                    "kill_switch_enabled"
                    if self.kill_switch_enabled
                    else ("paper_only_ready" if open_positions > 0 else "paper_only_idle")
                ),
                risk_alerts=alerts,
                last_run_id=last_run_id,
            )

        if self.last_backtest is None or self.last_backtest.equity_curve.empty:
            alerts = ["kill_switch_enabled"] if self.kill_switch_enabled else []
            return DashboardSummaryResponse(
                equity=0.0,
                daily_pnl=0.0,
                total_pnl=0.0,
                open_positions=0,
                system_status="kill_switch_enabled" if self.kill_switch_enabled else "paper_only_idle",
                risk_alerts=alerts,
                last_run_id=self.last_run_id,
            )

        equity_curve = self.last_backtest.equity_curve
        equity = float(equity_curve.iloc[-1])
        prev_equity = float(equity_curve.iloc[-2]) if len(equity_curve) > 1 else equity
        daily_pnl = equity - prev_equity
        total_pnl = equity - float(equity_curve.iloc[0])
        open_positions = int(self.last_backtest.position_series.iloc[-1] > 0.0)

        alerts = []
        if self.kill_switch_enabled:
            alerts.append("kill_switch_enabled")

        return DashboardSummaryResponse(
            equity=equity,
            daily_pnl=float(daily_pnl),
            total_pnl=float(total_pnl),
            open_positions=open_positions,
            system_status="kill_switch_enabled" if self.kill_switch_enabled else "paper_only_ready",
            risk_alerts=alerts,
            last_run_id=self.last_run_id,
        )

    def risk_status(self) -> RiskStatusResponse:
        """Return current risk status payload."""
        if self.repository is not None:
            self.kill_switch_enabled = self.repository.get_global_kill_switch()
        current_drawdown = 0.0
        gross_exposure = 0.0
        if self.last_backtest is not None and not self.last_backtest.equity_curve.empty:
            drawdown = _drawdown_series(self.last_backtest.equity_curve)
            current_drawdown = float(abs(drawdown.iloc[-1])) if not drawdown.empty else 0.0
            if not self.last_backtest.position_series.empty:
                gross_exposure = float(self.last_backtest.position_series.iloc[-1])

        return RiskStatusResponse(
            kill_switch_enabled=self.kill_switch_enabled,
            current_drawdown=current_drawdown,
            gross_exposure=gross_exposure,
            max_daily_loss=float(self.last_risk_config["max_daily_loss"]),
            max_position_size=float(self.last_risk_config["max_position_size"]),
            max_open_positions=int(self.last_risk_config["max_open_positions"]),
            max_gross_exposure=float(self.last_risk_config["max_gross_exposure"]),
            rejected_orders=list(self.rejected_orders),
        )

    def trades(self) -> TradesResponse:
        """Return serialized trade records from persistence or latest in-memory backtest."""
        if self.repository is not None:
            persisted_fills = self.repository.recent_fills(limit=200)
            records = [
                TradeRecord(
                    timestamp=pd.Timestamp(fill["timestamp"]).to_pydatetime(),
                    symbol=str(fill["symbol"]),
                    side=str(fill["side"]).upper(),
                    quantity=float(fill["quantity"]),
                    entry_price=float(fill["price"]),
                    exit_price=float(fill["price"]),
                    # Fill-level realized PnL is not available in current schema.
                    realized_pnl=0.0,
                    strategy=str(fill["strategy"]),
                    status="filled",
                )
                for fill in persisted_fills
            ]
            return TradesResponse(trades=records, total=len(records))

        if self.last_backtest is None:
            return TradesResponse(trades=[], total=0)
        records = _to_trade_records(
            result=self.last_backtest,
            symbol=self.last_backtest_symbol,
            strategy_name=self.last_backtest_strategy,
        )
        return TradesResponse(trades=records, total=len(records))

    def strategy_analytics(self) -> StrategyAnalyticsResponse:
        """Return strategy-level analytics built from persisted fills/runs."""
        snapshot = self._performance_snapshot()
        return StrategyAnalyticsResponse(
            generated_at=pd.Timestamp(snapshot.generated_at).to_pydatetime(),
            strategies=[_strategy_analytics_to_response(item) for item in snapshot.strategies],
        )

    def portfolio_analytics(self) -> PortfolioAnalyticsResponse:
        """Return portfolio-level analytics built from persisted state."""
        snapshot = self._performance_snapshot()
        portfolio = snapshot.portfolio
        return PortfolioAnalyticsResponse(
            generated_at=pd.Timestamp(snapshot.generated_at).to_pydatetime(),
            equity_curve=[
                EquityPoint(
                    timestamp=pd.Timestamp(point.timestamp).to_pydatetime(),
                    value=float(point.value),
                )
                for point in portfolio.equity_curve
            ],
            daily_pnl=[
                EquityPoint(
                    timestamp=pd.Timestamp(point.timestamp).to_pydatetime(),
                    value=float(point.value),
                )
                for point in portfolio.daily_pnl
            ],
            realized_pnl=float(portfolio.realized_pnl),
            unrealized_pnl=float(portfolio.unrealized_pnl),
            rolling_drawdown=[
                EquityPoint(
                    timestamp=pd.Timestamp(point.timestamp).to_pydatetime(),
                    value=float(point.value),
                )
                for point in portfolio.rolling_drawdown
            ],
            strategy_contribution=[
                StrategyContributionResponse(
                    strategy=item.strategy,
                    realized_pnl=float(item.realized_pnl),
                    return_pct=float(item.return_pct),
                    trades=int(item.trades),
                )
                for item in portfolio.strategy_contribution
            ],
            exposure_by_symbol=[
                SymbolExposureResponse(
                    symbol=item.symbol,
                    quantity=float(item.quantity),
                    avg_price=float(item.avg_price),
                    notional=float(item.notional),
                    unrealized_pnl=float(item.unrealized_pnl),
                )
                for item in portfolio.exposure_by_symbol
            ],
            open_risk_summary=OpenRiskSummaryResponse(
                open_positions=int(portfolio.open_risk_summary.open_positions),
                gross_exposure=float(portfolio.open_risk_summary.gross_exposure),
                largest_position_notional=float(portfolio.open_risk_summary.largest_position_notional),
                cash=float(portfolio.open_risk_summary.cash),
                day_start_equity=float(portfolio.open_risk_summary.day_start_equity),
                peak_equity=float(portfolio.open_risk_summary.peak_equity),
            ),
        )

    def context_analytics(self) -> ContextAnalyticsResponse:
        """Return context/regime analytics grouped across key dimensions."""
        snapshot = self._performance_snapshot()
        context = snapshot.context
        return ContextAnalyticsResponse(
            generated_at=pd.Timestamp(snapshot.generated_at).to_pydatetime(),
            by_symbol=[_context_bucket_to_response(item) for item in context.by_symbol],
            by_timeframe=[_context_bucket_to_response(item) for item in context.by_timeframe],
            by_weekday=[_context_bucket_to_response(item) for item in context.by_weekday],
            by_hour=[_context_bucket_to_response(item) for item in context.by_hour],
            by_regime=[_context_bucket_to_response(item) for item in context.by_regime],
        )

    def selection_status(self) -> SelectionStatusResponse:
        """Return latest deterministic strategy selection decision when available."""
        generated_at = pd.Timestamp.utcnow().to_pydatetime()
        latest_selection: dict[str, Any] | None = None
        if self.repository is not None:
            for run in self.repository.recent_runs(limit=50):
                service = str(run.get("service") or "")
                if not service.startswith("worker:"):
                    continue
                details = run.get("details")
                details_map = dict(details) if isinstance(details, dict) else {}
                selection = details_map.get("selection")
                if isinstance(selection, dict):
                    latest_selection = selection
                    generated_at = pd.Timestamp(
                        run.get("completed_at") or run.get("started_at") or pd.Timestamp.utcnow()
                    ).to_pydatetime()
                    break

        if latest_selection is None:
            return SelectionStatusResponse(
                generated_at=generated_at,
                regime="unknown",
                regime_signals={},
                selected_strategy=None,
                selected_score=0.0,
                minimum_score_threshold=0.0,
                sizing_multiplier=0.0,
                allocation_fraction=0.0,
                candidates=[],
            )

        candidates = latest_selection.get("candidates")
        candidate_rows: list[StrategyScoreResponse] = []
        if isinstance(candidates, list):
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                candidate_rows.append(
                    StrategyScoreResponse(
                        strategy=str(item.get("strategy") or ""),
                        signal=float(item.get("signal") or 0.0),
                        eligible=bool(item.get("eligible", False)),
                        reasons=[str(reason) for reason in item.get("reasons", [])],
                        score=float(item.get("score") or 0.0),
                        recent_expectancy=float(item.get("recent_expectancy") or 0.0),
                        recent_sharpe=float(item.get("recent_sharpe") or 0.0),
                        win_rate=float(item.get("win_rate") or 0.0),
                        drawdown_penalty=float(item.get("drawdown_penalty") or 0.0),
                        regime_fit=float(item.get("regime_fit") or 0.0),
                        sizing_multiplier=float(item.get("sizing_multiplier") or 0.0),
                    )
                )

        regime_signals = latest_selection.get("regime_signals")
        return SelectionStatusResponse(
            generated_at=generated_at,
            regime=str(latest_selection.get("regime") or "unknown"),
            regime_signals={
                str(key): float(value)
                for key, value in (regime_signals.items() if isinstance(regime_signals, dict) else [])
            },
            selected_strategy=(
                str(latest_selection.get("selected_strategy"))
                if latest_selection.get("selected_strategy") is not None
                else None
            ),
            selected_score=float(latest_selection.get("selected_score") or 0.0),
            minimum_score_threshold=float(latest_selection.get("minimum_score_threshold") or 0.0),
            sizing_multiplier=float(latest_selection.get("sizing_multiplier") or 0.0),
            allocation_fraction=float(latest_selection.get("allocation_fraction") or 0.0),
            candidates=candidate_rows,
        )

    def system_status(self) -> ServiceStatusResponse:
        """Return service-level operational status for deployment checks."""
        database_ok = True
        worker_heartbeat: dict[str, Any] | None = None
        recent_runs: list[dict[str, Any]] = []
        if self.repository is not None:
            self.kill_switch_enabled = self.repository.get_global_kill_switch()
            try:
                database_ok = self.repository.healthcheck()
            except Exception:
                database_ok = False
            worker_name = (
                self.deployment_settings.worker_name
                if self.deployment_settings is not None
                else "default-worker"
            )
            worker_heartbeat = self.repository.get_worker_heartbeat(worker_name)
            recent_runs = self.repository.recent_runs(limit=10)

        return ServiceStatusResponse(
            service_name=(
                self.deployment_settings.service_name
                if self.deployment_settings is not None
                else "theta-web"
            ),
            app_env=(
                self.deployment_settings.app_env
                if self.deployment_settings is not None
                else "development"
            ),
            database_ok=database_ok,
            kill_switch_enabled=self.kill_switch_enabled,
            paper_trading_enabled=(
                self.deployment_settings.paper_trading_enabled
                if self.deployment_settings is not None
                else False
            ),
            worker_enable_trading=(
                self.deployment_settings.worker_enable_trading
                if self.deployment_settings is not None
                else False
            ),
            worker_heartbeat=worker_heartbeat,
            recent_runs=recent_runs,
            timestamp=pd.Timestamp.utcnow().to_pydatetime(),
        )

    def set_kill_switch(self, enabled: bool) -> KillSwitchResponse:
        """Enable or disable kill switch for API-level operations."""
        self.kill_switch_enabled = enabled
        if self.repository is not None:
            self.repository.set_global_kill_switch(
                enabled=enabled,
                reason="api_manual_toggle",
            )
            self.repository.append_log_event(
                level="WARNING" if enabled else "INFO",
                logger_name=LOGGER.name,
                event="api_kill_switch_toggled",
                payload={"enabled": enabled},
            )
        if enabled:
            self.rejected_orders.append("kill_switch_manually_enabled")
            LOGGER.warning("api_kill_switch_enabled")
        else:
            LOGGER.info("api_kill_switch_disabled")
        return KillSwitchResponse(
            kill_switch_enabled=self.kill_switch_enabled,
            updated_at=pd.Timestamp.utcnow().to_pydatetime(),
        )
