"""Background worker for unattended paper-trading execution loops."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import time
from uuid import uuid4

import pandas as pd

from src.analytics.performance_layer import PerformanceAnalyticsSnapshot, build_performance_snapshot
from src.config.deployment import DeploymentSettings
from src.data.cache import DataCache
from src.data.loaders import HistoricalDataLoader
from src.data.providers.factory import make_market_data_provider_from_env
from src.execution.executor import PaperTradingExecutor
from src.execution.models import Order, Position
from src.observability import clear_run, configure_logging, start_run
from src.persistence import PortfolioSnapshot, PersistenceRepository
from src.risk.manager import RiskManager
from src.selection import (
    GlobalSelectionState,
    SelectionConfig,
    SelectionDecision,
    StrategyCandidate,
    StrategySelector,
    classify_regime,
    strategy_compatible_regimes,
)
from src.strategies import create_strategy, list_strategies

LOGGER = logging.getLogger("theta.worker.service")
EPSILON = 1e-12


def _build_loader(cache_dir: str) -> HistoricalDataLoader:
    """Create worker loader using configured provider abstractions."""
    provider = make_market_data_provider_from_env()
    cache = DataCache(root_dir=Path(cache_dir))
    return HistoricalDataLoader(provider=provider, cache=cache)


@dataclass(slots=True)
class TradingWorker:
    """Run a continuous paper-trading loop with persistence and risk guards."""

    settings: DeploymentSettings
    repository: PersistenceRepository
    loader: HistoricalDataLoader = field(init=False)
    selector: StrategySelector = field(
        default_factory=lambda: StrategySelector(config=SelectionConfig())
    )

    def __post_init__(self) -> None:
        self.loader = _build_loader(cache_dir=self.settings.cache_dir)
        self.repository.initialize(starting_cash=self.settings.initial_capital)

    def run_forever(self) -> None:
        """Run worker loop until process termination."""
        configure_logging(log_dir=self.settings.log_dir)

        if self.settings.kill_switch_on_startup:
            self.repository.set_global_kill_switch(
                True,
                reason="kill_switch_on_startup",
            )

        LOGGER.info(
            "worker_start service=%s worker_name=%s paper_trading=%s worker_enable_trading=%s poll_seconds=%d",
            self.settings.service_name,
            self.settings.worker_name,
            self.settings.paper_trading_enabled,
            self.settings.worker_enable_trading,
            self.settings.worker_poll_seconds,
        )
        self.repository.append_log_event(
            level="INFO",
            logger_name=LOGGER.name,
            event="worker_start",
            payload={
                "service": self.settings.service_name,
                "worker_name": self.settings.worker_name,
                "paper_trading_enabled": self.settings.paper_trading_enabled,
                "worker_enable_trading": self.settings.worker_enable_trading,
            },
        )

        while True:
            self.run_once()
            time.sleep(self.settings.worker_poll_seconds)

    def run_once(self) -> None:
        """Execute one worker cycle with idempotency and error capture."""
        cycle_timestamp = pd.Timestamp.utcnow()
        cycle_key = self._cycle_key(cycle_timestamp)
        service_key = f"worker:{self.settings.worker_name}"

        self.repository.record_worker_heartbeat(
            worker_name=self.settings.worker_name,
            status="heartbeat",
            last_cycle_key=cycle_key,
            message="cycle_start",
        )

        if self.repository.get_global_kill_switch():
            LOGGER.warning("worker_cycle_skipped reason=kill_switch_enabled cycle_key=%s", cycle_key)
            self.repository.append_log_event(
                level="WARNING",
                logger_name=LOGGER.name,
                event="worker_cycle_skipped",
                payload={"cycle_key": cycle_key, "reason": "kill_switch_enabled"},
            )
            self.repository.record_worker_heartbeat(
                worker_name=self.settings.worker_name,
                status="paused",
                last_cycle_key=cycle_key,
                message="kill_switch_enabled",
            )
            return

        if not self.settings.paper_trading_enabled or not self.settings.worker_enable_trading:
            LOGGER.info(
                "worker_cycle_skipped reason=paper_or_worker_disabled cycle_key=%s paper=%s worker=%s",
                cycle_key,
                self.settings.paper_trading_enabled,
                self.settings.worker_enable_trading,
            )
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="worker_cycle_skipped",
                payload={
                    "cycle_key": cycle_key,
                    "reason": "paper_or_worker_disabled",
                    "paper_trading_enabled": self.settings.paper_trading_enabled,
                    "worker_enable_trading": self.settings.worker_enable_trading,
                },
            )
            self.repository.record_worker_heartbeat(
                worker_name=self.settings.worker_name,
                status="idle",
                last_cycle_key=cycle_key,
                message="paper_or_worker_disabled",
            )
            return

        run_id = f"worker-{uuid4().hex}"
        if not self.repository.start_run(
            run_id=run_id,
            service=service_key,
            cycle_key=cycle_key,
            symbol=self.settings.worker_symbol,
            timeframe=self.settings.worker_timeframe,
            strategy="strategy_selector",
            details={"source": "worker_cycle"},
        ):
            LOGGER.info("worker_cycle_skipped reason=duplicate_cycle cycle_key=%s", cycle_key)
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="worker_cycle_skipped",
                payload={"cycle_key": cycle_key, "reason": "duplicate_cycle"},
            )
            self.repository.record_worker_heartbeat(
                worker_name=self.settings.worker_name,
                status="duplicate",
                last_cycle_key=cycle_key,
                message="duplicate_cycle",
            )
            return

        start_run(run_id=run_id)
        try:
            data = self.loader.load(
                symbol=self.settings.worker_symbol,
                timeframe=self.settings.worker_timeframe,
                force_refresh=self.settings.worker_force_refresh,
            )
            latest_price = float(data["close"].iloc[-1])
            latest_timestamp = pd.Timestamp(data.index[-1])

            risk_manager = RiskManager(
                max_position_size=self.settings.max_position_size,
                max_daily_loss=self.settings.max_daily_loss,
                max_open_positions=self.settings.max_open_positions,
                trading_start=self.settings.trading_start,
                trading_end=self.settings.trading_end,
                allow_after_hours=self.settings.allow_after_hours,
            )
            executor = PaperTradingExecutor(
                starting_cash=self.settings.initial_capital,
                risk_manager=risk_manager,
                paper_trading_enabled=self.settings.paper_trading_enabled,
                max_notional_per_trade=self.settings.max_notional_per_trade,
                max_open_positions=self.settings.max_open_positions,
                daily_loss_cap=self.settings.executor_daily_loss_cap,
            )

            snapshot = self.repository.load_portfolio_snapshot(
                default_cash=self.settings.initial_capital
            )
            executor.restore_state(
                cash=snapshot.cash,
                day_start_equity=snapshot.day_start_equity,
                peak_equity=snapshot.peak_equity,
                positions=snapshot.positions,
                kill_switch_enabled=self.repository.get_global_kill_switch(),
            )

            performance_snapshot = self._build_performance_snapshot(snapshot)
            regime = classify_regime(data)
            LOGGER.info(
                "regime_classified cycle_key=%s regime=%s ma_slope=%.6f price_vs_ma=%.6f atr_pct=%.6f persistence=%.6f",
                cycle_key,
                regime.state,
                regime.moving_average_slope,
                regime.price_vs_moving_average,
                regime.atr_pct,
                regime.directional_persistence,
            )
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="regime_classified",
                run_id=run_id,
                payload={
                    "cycle_key": cycle_key,
                    "regime": regime.state,
                    **regime.as_signals(),
                },
            )

            candidates = self._build_strategy_candidates(
                data=data,
                analytics=performance_snapshot,
            )
            selection_state = self._build_global_selection_state(
                executor=executor,
                latest_price=latest_price,
            )
            decision = self.selector.select(
                regime=regime,
                candidates=candidates,
                global_state=selection_state,
            )

            self._log_selection_decision(run_id=run_id, cycle_key=cycle_key, decision=decision)

            selected_signal = 0.0
            if decision.selected_strategy is not None:
                selected_entry = next(
                    (item for item in decision.candidates if item.strategy == decision.selected_strategy),
                    None,
                )
                if selected_entry is not None:
                    selected_signal = float(selected_entry.signal)

            order = self._build_order(
                selected_strategy=decision.selected_strategy,
                selected_signal=selected_signal,
                latest_price=latest_price,
                latest_timestamp=latest_timestamp,
                current_position=executor.positions.get(self.settings.worker_symbol),
                sizing_multiplier=decision.sizing_multiplier,
            )

            if order is None:
                self.repository.append_log_event(
                    level="INFO",
                    logger_name=LOGGER.name,
                    event="worker_no_order",
                    run_id=run_id,
                    payload={
                        "cycle_key": cycle_key,
                        "selection": decision.as_dict(),
                    },
                )
                self.repository.finish_run(
                    run_id=run_id,
                    status="completed",
                    details={
                        "selection": decision.as_dict(),
                        "action": "no_order",
                    },
                )
                self.repository.record_worker_heartbeat(
                    worker_name=self.settings.worker_name,
                    status="ok",
                    last_cycle_key=cycle_key,
                    message="no_order",
                )
                return

            dedupe_key = self.repository.compute_order_dedupe_key(cycle_key, order)
            if self.repository.order_exists_by_dedupe_key(dedupe_key):
                self.repository.append_log_event(
                    level="INFO",
                    logger_name=LOGGER.name,
                    event="worker_duplicate_order_skipped",
                    run_id=run_id,
                    payload={
                        "cycle_key": cycle_key,
                        "dedupe_key": dedupe_key,
                        "selection": decision.as_dict(),
                    },
                )
                self.repository.finish_run(
                    run_id=run_id,
                    status="completed",
                    details={
                        "selection": decision.as_dict(),
                        "action": "duplicate_order_skipped",
                    },
                )
                self.repository.record_worker_heartbeat(
                    worker_name=self.settings.worker_name,
                    status="duplicate",
                    last_cycle_key=cycle_key,
                    message="duplicate_order_skipped",
                )
                return

            self.repository.record_order(
                order=order,
                source="worker",
                run_id=run_id,
                dedupe_key=dedupe_key,
            )
            result = executor.submit_order(order)
            self.repository.update_order_status(
                order_id=result.order_id,
                status=result.status,
                rejection_reasons=result.rejection_reasons,
            )
            if result.status == "FILLED":
                fill = executor.filled_orders[-1]
                self.repository.record_fill(fill=fill, run_id=run_id)

            self.repository.append_log_event(
                level="INFO" if result.status == "FILLED" else "WARNING",
                logger_name=LOGGER.name,
                event="worker_order_processed",
                run_id=run_id,
                payload={
                    "cycle_key": cycle_key,
                    "order_id": result.order_id,
                    "status": result.status,
                    "rejection_reasons": list(result.rejection_reasons),
                    "selection": decision.as_dict(),
                },
            )

            cash, day_start_equity, peak_equity, positions = executor.snapshot_state()
            self.repository.save_portfolio_snapshot(
                PortfolioSnapshot(
                    cash=cash,
                    day_start_equity=day_start_equity,
                    peak_equity=peak_equity,
                    positions=positions,
                )
            )

            if executor.kill_switch_enabled:
                self.repository.set_global_kill_switch(
                    True,
                    reason="worker_runtime_kill_switch",
                )

            self.repository.finish_run(
                run_id=run_id,
                status="completed",
                details={
                    "selection": decision.as_dict(),
                    "order_id": result.order_id,
                    "order_status": result.status,
                    "rejection_reasons": list(result.rejection_reasons),
                },
            )
            self.repository.record_worker_heartbeat(
                worker_name=self.settings.worker_name,
                status="ok",
                last_cycle_key=cycle_key,
                message=f"strategy={decision.selected_strategy or 'none'} order={result.status}",
            )
        except Exception as exc:
            LOGGER.exception("worker_cycle_failed cycle_key=%s error=%s", cycle_key, exc)
            self.repository.finish_run(
                run_id=run_id,
                status="failed",
                error_message=str(exc),
            )
            self.repository.append_log_event(
                level="ERROR",
                logger_name=LOGGER.name,
                event="worker_cycle_failed",
                run_id=run_id,
                payload={"cycle_key": cycle_key, "error": str(exc)},
            )
            self.repository.record_worker_heartbeat(
                worker_name=self.settings.worker_name,
                status="error",
                last_cycle_key=cycle_key,
                message=str(exc)[:250],
            )
        finally:
            clear_run()

    def _build_performance_snapshot(
        self,
        snapshot: PortfolioSnapshot,
    ) -> PerformanceAnalyticsSnapshot:
        """Build analytics snapshot from persisted fills/runs for selection + API parity."""
        fills = self.repository.recent_fills(limit=5000)
        runs = self.repository.recent_runs(limit=2000)
        return build_performance_snapshot(
            fills=fills,
            runs=runs,
            portfolio_snapshot=snapshot,
            starting_equity=self.settings.initial_capital,
        )

    def _build_strategy_candidates(
        self,
        data: pd.DataFrame,
        analytics: PerformanceAnalyticsSnapshot,
    ) -> list[StrategyCandidate]:
        """Build normalized candidate inputs for all registered strategies."""
        persisted_configs = self.repository.load_strategy_configs()
        metrics_by_strategy = analytics.strategies_by_name

        candidates: list[StrategyCandidate] = []
        for strategy_name in list_strategies():
            persisted = persisted_configs.get(strategy_name, {})
            enabled = str(persisted.get("status", "enabled")) == "enabled"
            params = self._resolve_strategy_parameters(strategy_name, persisted)

            required_data_available = True
            latest_signal = 0.0
            if enabled:
                try:
                    strategy = create_strategy(strategy_name, **params)
                    signals = strategy.generate_signals(data)
                    latest_signal = float(signals["signal"].iloc[-1]) if not signals.empty else 0.0
                except Exception:
                    required_data_available = False
                    latest_signal = 0.0

            strategy_metrics = metrics_by_strategy.get(strategy_name)
            if strategy_metrics is None:
                recent_expectancy = 0.0
                recent_sharpe = 0.0
                recent_win_rate = 0.0
                recent_drawdown = 0.0
                recent_trades = 0
            else:
                recent_expectancy = float(strategy_metrics.last_20.expectancy)
                recent_sharpe = float(strategy_metrics.last_20.sharpe)
                recent_win_rate = float(strategy_metrics.last_20.win_rate)
                recent_drawdown = float(strategy_metrics.max_drawdown)
                recent_trades = int(strategy_metrics.last_20.trades)

            candidates.append(
                StrategyCandidate(
                    strategy=strategy_name,
                    enabled=enabled,
                    signal=latest_signal,
                    recent_expectancy=recent_expectancy,
                    recent_sharpe=recent_sharpe,
                    recent_win_rate=recent_win_rate,
                    recent_drawdown=recent_drawdown,
                    recent_trades=recent_trades,
                    required_data_available=required_data_available,
                    compatible_regimes=strategy_compatible_regimes(strategy_name),
                    signal_confidence=min(max(abs(latest_signal), 0.0), 1.0),
                )
            )

        return candidates

    def _resolve_strategy_parameters(
        self,
        strategy_name: str,
        persisted: dict[str, object],
    ) -> dict[str, object]:
        """Resolve merged strategy parameters from worker config + persisted defaults."""
        merged: dict[str, object] = {}
        if strategy_name == self.settings.worker_strategy:
            merged.update(self.settings.worker_strategy_params)

        persisted_params = persisted.get("parameters")
        if isinstance(persisted_params, dict):
            merged.update(persisted_params)
        return merged

    def _build_global_selection_state(
        self,
        executor: PaperTradingExecutor,
        latest_price: float,
    ) -> GlobalSelectionState:
        """Compute global gating state for deterministic eligibility checks."""
        current_equity = executor.current_equity()
        required_notional = float(self.settings.worker_order_quantity * latest_price)
        max_position_notional = float(self.settings.max_position_size * current_equity)
        available_notional = float(min(self.settings.max_notional_per_trade, max_position_notional))

        active_positions = sum(1 for item in executor.positions.values() if item.quantity > EPSILON)
        has_worker_symbol_position = (
            executor.positions.get(self.settings.worker_symbol) is not None
            and float(executor.positions[self.settings.worker_symbol].quantity) > EPSILON
        )
        max_positions_breached = (
            active_positions >= self.settings.max_open_positions and not has_worker_symbol_position
        )

        return GlobalSelectionState(
            kill_switch_enabled=self.repository.get_global_kill_switch(),
            paper_trading_enabled=self.settings.paper_trading_enabled,
            worker_enable_trading=self.settings.worker_enable_trading,
            risk_budget_available=(
                required_notional <= available_notional + EPSILON
                and required_notional <= executor.cash + EPSILON
            ),
            max_positions_breached=max_positions_breached,
        )

    def _log_selection_decision(
        self,
        run_id: str,
        cycle_key: str,
        decision: SelectionDecision,
    ) -> None:
        """Emit structured selection logs for auditability and debugging."""
        for candidate in decision.candidates:
            LOGGER.info(
                "strategy_eligibility_decision cycle_key=%s strategy=%s eligible=%s reasons=%s",
                cycle_key,
                candidate.strategy,
                candidate.eligible,
                ",".join(candidate.reasons) if candidate.reasons else "none",
            )
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="strategy_eligibility_decision",
                run_id=run_id,
                payload={
                    "cycle_key": cycle_key,
                    "strategy": candidate.strategy,
                    "eligible": candidate.eligible,
                    "reasons": list(candidate.reasons),
                },
            )

            LOGGER.info(
                "strategy_score cycle_key=%s strategy=%s score=%.6f expectancy=%.6f sharpe=%.6f win_rate=%.6f regime_fit=%.6f drawdown_penalty=%.6f",
                cycle_key,
                candidate.strategy,
                candidate.score,
                candidate.recent_expectancy,
                candidate.recent_sharpe,
                candidate.win_rate,
                candidate.regime_fit,
                candidate.drawdown_penalty,
            )
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="strategy_score",
                run_id=run_id,
                payload={
                    "cycle_key": cycle_key,
                    "strategy": candidate.strategy,
                    "score": float(candidate.score),
                    "expectancy": float(candidate.recent_expectancy),
                    "sharpe": float(candidate.recent_sharpe),
                    "win_rate": float(candidate.win_rate),
                    "regime_fit": float(candidate.regime_fit),
                    "drawdown_penalty": float(candidate.drawdown_penalty),
                },
            )

            if decision.selected_strategy != candidate.strategy:
                self.repository.append_log_event(
                    level="INFO",
                    logger_name=LOGGER.name,
                    event="strategy_rejected",
                    run_id=run_id,
                    payload={
                        "cycle_key": cycle_key,
                        "strategy": candidate.strategy,
                        "reasons": list(candidate.reasons),
                    },
                )

        LOGGER.info(
            "strategy_selected cycle_key=%s strategy=%s score=%.6f",
            cycle_key,
            decision.selected_strategy or "none",
            decision.selected_score,
        )
        self.repository.append_log_event(
            level="INFO",
            logger_name=LOGGER.name,
            event="strategy_selected",
            run_id=run_id,
            payload={
                "cycle_key": cycle_key,
                "selected_strategy": decision.selected_strategy,
                "selected_score": float(decision.selected_score),
                "regime": decision.regime,
            },
        )

        LOGGER.info(
            "sizing_decision cycle_key=%s strategy=%s sizing_multiplier=%.4f allocation_fraction=%.4f",
            cycle_key,
            decision.selected_strategy or "none",
            decision.sizing_multiplier,
            decision.allocation_fraction,
        )
        self.repository.append_log_event(
            level="INFO",
            logger_name=LOGGER.name,
            event="sizing_decision",
            run_id=run_id,
            payload={
                "cycle_key": cycle_key,
                "selected_strategy": decision.selected_strategy,
                "sizing_multiplier": float(decision.sizing_multiplier),
                "allocation_fraction": float(decision.allocation_fraction),
            },
        )

    def _build_order(
        self,
        selected_strategy: str | None,
        selected_signal: float,
        latest_price: float,
        latest_timestamp: pd.Timestamp,
        current_position: Position | None,
        sizing_multiplier: float,
    ) -> Order | None:
        """Convert selected strategy + current position into one order instruction."""
        current_qty = 0.0 if current_position is None else float(current_position.quantity)

        if selected_strategy is not None and selected_signal > EPSILON and current_qty <= EPSILON:
            quantity = float(self.settings.worker_order_quantity * max(sizing_multiplier, 0.0))
            if quantity <= EPSILON:
                return None
            return Order(
                symbol=self.settings.worker_symbol,
                side="BUY",
                quantity=quantity,
                price=latest_price,
                timestamp=latest_timestamp,
            )

        if (selected_strategy is None or selected_signal <= EPSILON) and current_qty > EPSILON:
            return Order(
                symbol=self.settings.worker_symbol,
                side="SELL",
                quantity=current_qty,
                price=latest_price,
                timestamp=latest_timestamp,
            )
        return None

    def _cycle_key(self, timestamp: pd.Timestamp) -> str:
        """Derive cycle key for idempotency based on timeframe granularity."""
        if self.settings.worker_timeframe.endswith("d"):
            return f"{self.settings.worker_symbol}:{self.settings.worker_timeframe}:{timestamp.strftime('%Y-%m-%d')}"
        return (
            f"{self.settings.worker_symbol}:{self.settings.worker_timeframe}:"
            f"{timestamp.floor('min').strftime('%Y-%m-%dT%H:%M')}"
        )
