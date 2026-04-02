"""Service layer for API handlers."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, field
import logging
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pandas as pd

from src.config.deployment import DeploymentSettings
from src.api.schemas import (
    BacktestRunRequest,
    BacktestRunResponse,
    DashboardSummaryResponse,
    EquityPoint,
    KillSwitchResponse,
    RiskStatusResponse,
    ServiceStatusResponse,
    StrategySummary,
    TradeRecord,
    TradesResponse,
)
from src.backtest.engine import BacktestResult
from src.cli.services import run_backtest as run_backtest_workflow
from src.observability import clear_run, configure_logging, start_run
from src.persistence import PersistenceRepository
from src.strategies import get_strategy_class, list_strategies

LOGGER = logging.getLogger("theta.api.services")


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
            "max_position_size": 1.0,
            "max_open_positions": 10.0,
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
            "max_position_size": 1.0,
            "max_open_positions": 10.0,
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
                position_size_pct=request.position_size_pct,
                fixed_fee=request.fixed_fee,
                slippage_pct=request.slippage_pct,
                stop_loss_pct=request.stop_loss_pct,
                take_profit_pct=request.take_profit_pct,
                max_position_size=request.max_position_size,
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
                "max_position_size": float(request.max_position_size),
                "max_open_positions": float(10),
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
                metrics={key: float(value) for key, value in result.metrics.items()},
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
        """Return current dashboard summary from latest backtest snapshot."""
        if self.repository is not None:
            self.kill_switch_enabled = self.repository.get_global_kill_switch()
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
        """Return serialized trades from most recent backtest."""
        if self.last_backtest is None:
            return TradesResponse(trades=[], total=0)
        records = _to_trade_records(
            result=self.last_backtest,
            symbol=self.last_backtest_symbol,
            strategy_name=self.last_backtest_strategy,
        )
        return TradesResponse(trades=records, total=len(records))

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
