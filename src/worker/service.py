"""Background worker for unattended paper-trading execution loops."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import time
from uuid import uuid4

import pandas as pd

from src.config.deployment import DeploymentSettings
from src.data.cache import DataCache
from src.data.loaders import HistoricalDataLoader
from src.data.providers.synthetic import SyntheticMarketDataProvider
from src.execution.executor import PaperTradingExecutor
from src.execution.models import Order
from src.observability import clear_run, configure_logging, start_run
from src.persistence import PortfolioSnapshot, PersistenceRepository
from src.risk.manager import RiskManager
from src.strategies import create_strategy

LOGGER = logging.getLogger("theta.worker.service")


def _build_loader(cache_dir: str) -> HistoricalDataLoader:
    """Create a worker data loader using existing provider abstractions."""
    provider = SyntheticMarketDataProvider()
    cache = DataCache(root_dir=Path(cache_dir))
    return HistoricalDataLoader(provider=provider, cache=cache)


@dataclass(slots=True)
class TradingWorker:
    """Run a continuous paper-trading loop with persistence and risk guards."""

    settings: DeploymentSettings
    repository: PersistenceRepository
    loader: HistoricalDataLoader = field(init=False)

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
            strategy=self.settings.worker_strategy,
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
            strategy_name, strategy_params = self._resolve_strategy_config()
            strategy = create_strategy(strategy_name, **strategy_params)
            signals = strategy.generate_signals(data)
            latest_signal = float(signals["signal"].iloc[-1]) if not signals.empty else 0.0
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

            order = self._build_order(
                latest_signal=latest_signal,
                latest_price=latest_price,
                latest_timestamp=latest_timestamp,
                current_position=executor.positions.get(self.settings.worker_symbol),
            )
            if order is None:
                self.repository.append_log_event(
                    level="INFO",
                    logger_name=LOGGER.name,
                    event="worker_no_order",
                    run_id=run_id,
                    payload={"signal": latest_signal, "cycle_key": cycle_key},
                )
                self.repository.finish_run(
                    run_id=run_id,
                    status="completed",
                    details={
                        "signal": latest_signal,
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
                    payload={"cycle_key": cycle_key, "dedupe_key": dedupe_key},
                )
                self.repository.finish_run(
                    run_id=run_id,
                    status="completed",
                    details={
                        "signal": latest_signal,
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
                    "signal": latest_signal,
                    "order_id": result.order_id,
                    "order_status": result.status,
                    "rejection_reasons": list(result.rejection_reasons),
                },
            )
            self.repository.record_worker_heartbeat(
                worker_name=self.settings.worker_name,
                status="ok",
                last_cycle_key=cycle_key,
                message=f"order_status={result.status}",
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

    def _resolve_strategy_config(self) -> tuple[str, dict[str, object]]:
        """Resolve active strategy name + parameters from persisted config."""
        strategy_name = self.settings.worker_strategy
        params = dict(self.settings.worker_strategy_params)
        persisted = self.repository.load_strategy_configs().get(strategy_name)
        if persisted is None:
            return strategy_name, params
        if str(persisted.get("status", "enabled")) == "disabled":
            raise PermissionError(f"Strategy '{strategy_name}' is disabled")
        persisted_params = persisted.get("parameters", {})
        if isinstance(persisted_params, dict):
            merged = dict(params)
            merged.update(persisted_params)
            params = merged
        return strategy_name, params

    def _build_order(
        self,
        latest_signal: float,
        latest_price: float,
        latest_timestamp: pd.Timestamp,
        current_position: Position | None,
    ) -> Order | None:
        """Convert latest signal + position state into one order instruction."""
        current_qty = 0.0 if current_position is None else float(current_position.quantity)
        if latest_signal > 0.0 and current_qty <= 0.0:
            return Order(
                symbol=self.settings.worker_symbol,
                side="BUY",
                quantity=float(self.settings.worker_order_quantity),
                price=latest_price,
                timestamp=latest_timestamp,
            )
        if latest_signal <= 0.0 and current_qty > 0.0:
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
