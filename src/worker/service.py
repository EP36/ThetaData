"""Background worker for unattended paper-trading execution loops."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import time
from typing import cast
from uuid import uuid4

import pandas as pd

from src.analytics.performance_layer import (
    PerformanceAnalyticsSnapshot,
    build_performance_snapshot,
)
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
from src.worker.universe import (
    UniverseMode,
    UniverseScanResult,
    UniverseScanner,
    UniverseScannerConfig,
)

LOGGER = logging.getLogger("theta.worker.service")
EPSILON = 1e-12


def _build_loader(cache_dir: str) -> HistoricalDataLoader:
    """Create worker loader using configured provider abstractions."""
    provider = make_market_data_provider_from_env()
    cache = DataCache(root_dir=Path(cache_dir))
    return HistoricalDataLoader(provider=provider, cache=cache)


@dataclass(frozen=True, slots=True)
class SymbolCycleSummary:
    """Result summary for one symbol processed in one worker cycle."""

    symbol: str
    run_id: str | None
    status: str
    action: str
    selected_strategy: str | None
    active_strategy: str | None
    order_status: str | None
    no_trade_reason: str | None
    rejection_reasons: tuple[str, ...]


@dataclass(slots=True)
class TradingWorker:
    """Run a continuous paper-trading loop with persistence and risk guards."""

    settings: DeploymentSettings
    repository: PersistenceRepository
    loader: HistoricalDataLoader = field(init=False)
    universe_scanner: UniverseScanner = field(init=False)
    selector: StrategySelector = field(
        default_factory=lambda: StrategySelector(config=SelectionConfig())
    )

    def __post_init__(self) -> None:
        self.loader = _build_loader(cache_dir=self.settings.cache_dir)
        self.universe_scanner = UniverseScanner(
            loader=self.loader,
            config=UniverseScannerConfig(
                timeframe=self.settings.worker_timeframe,
                max_candidates=self.settings.worker_max_candidates,
                min_price=self.settings.min_price,
                min_average_volume=self.settings.min_avg_volume,
                min_relative_volume=self.settings.min_relative_volume,
                max_spread_pct=self.settings.max_spread_pct,
            ),
        )
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
            "worker_start service=%s worker_name=%s paper_trading=%s worker_enable_trading=%s worker_dry_run=%s poll_seconds=%d universe_mode=%s universe=%s",
            self.settings.service_name,
            self.settings.worker_name,
            self.settings.paper_trading_enabled,
            self.settings.worker_enable_trading,
            self.settings.worker_dry_run,
            self.settings.worker_poll_seconds,
            self.settings.worker_universe_mode,
            ",".join(self.settings.worker_symbols),
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
                "worker_dry_run": self.settings.worker_dry_run,
                "universe_mode": self.settings.worker_universe_mode,
                "universe": list(self.settings.worker_symbols),
                "worker_max_candidates": self.settings.worker_max_candidates,
                "min_price": self.settings.min_price,
                "min_avg_volume": self.settings.min_avg_volume,
                "min_relative_volume": self.settings.min_relative_volume,
                "max_spread_pct": self.settings.max_spread_pct,
                "allow_multi_strategy_per_symbol": self.settings.worker_allow_multi_strategy_per_symbol,
            },
        )

        while True:
            self.run_once()
            time.sleep(self.settings.worker_poll_seconds)

    def run_once(self) -> None:
        """Execute one worker cycle across the configured symbol universe."""
        cycle_timestamp = pd.Timestamp.utcnow()
        heartbeat_cycle_key = self._heartbeat_cycle_key(cycle_timestamp)
        configured_universe = tuple(self.settings.worker_symbols)

        self.repository.record_worker_heartbeat(
            worker_name=self.settings.worker_name,
            status="heartbeat",
            last_cycle_key=heartbeat_cycle_key,
            message=(
                f"cycle_start mode={self.settings.worker_universe_mode} "
                f"configured={','.join(configured_universe)}"
            ),
        )

        if self.repository.get_global_kill_switch():
            LOGGER.warning(
                "worker_cycle_skipped reason=kill_switch_enabled cycle_key=%s",
                heartbeat_cycle_key,
            )
            self.repository.append_log_event(
                level="WARNING",
                logger_name=LOGGER.name,
                event="worker_cycle_skipped",
                payload={
                    "cycle_key": heartbeat_cycle_key,
                    "reason": "kill_switch_enabled",
                    "universe_mode": self.settings.worker_universe_mode,
                    "configured_universe": list(configured_universe),
                },
            )
            self.repository.record_worker_heartbeat(
                worker_name=self.settings.worker_name,
                status="paused",
                last_cycle_key=heartbeat_cycle_key,
                message="kill_switch_enabled",
            )
            return

        if not self.settings.worker_enable_trading:
            LOGGER.info(
                "worker_cycle_skipped reason=worker_disabled cycle_key=%s",
                heartbeat_cycle_key,
            )
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="worker_cycle_skipped",
                payload={
                    "cycle_key": heartbeat_cycle_key,
                    "reason": "worker_disabled",
                    "paper_trading_enabled": self.settings.paper_trading_enabled,
                    "worker_enable_trading": self.settings.worker_enable_trading,
                    "worker_dry_run": self.settings.worker_dry_run,
                    "universe_mode": self.settings.worker_universe_mode,
                    "configured_universe": list(configured_universe),
                },
            )
            self.repository.record_worker_heartbeat(
                worker_name=self.settings.worker_name,
                status="idle",
                last_cycle_key=heartbeat_cycle_key,
                message="worker_disabled",
            )
            return

        if not self.settings.paper_trading_enabled and not self.settings.worker_dry_run:
            LOGGER.info(
                "worker_cycle_skipped reason=paper_disabled_without_dry_run cycle_key=%s",
                heartbeat_cycle_key,
            )
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="worker_cycle_skipped",
                payload={
                    "cycle_key": heartbeat_cycle_key,
                    "reason": "paper_disabled_without_dry_run",
                    "paper_trading_enabled": self.settings.paper_trading_enabled,
                    "worker_enable_trading": self.settings.worker_enable_trading,
                    "worker_dry_run": self.settings.worker_dry_run,
                    "universe_mode": self.settings.worker_universe_mode,
                    "configured_universe": list(configured_universe),
                },
            )
            self.repository.record_worker_heartbeat(
                worker_name=self.settings.worker_name,
                status="idle",
                last_cycle_key=heartbeat_cycle_key,
                message="paper_disabled_without_dry_run",
            )
            return

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
            paper_trading_enabled=(
                self.settings.paper_trading_enabled and not self.settings.worker_dry_run
            ),
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
        lock_rows = self.repository.list_symbol_strategy_locks()
        symbol_strategy_locks: dict[str, str] = {
            symbol: str(details.get("strategy") or "")
            for symbol, details in lock_rows.items()
            if str(details.get("strategy") or "").strip()
        }

        self._release_stale_locks(
            executor=executor,
            symbol_strategy_locks=symbol_strategy_locks,
        )

        scan_result = self.universe_scanner.scan(
            mode=cast(UniverseMode, self.settings.worker_universe_mode),
            configured_symbols=configured_universe,
            force_refresh=self.settings.worker_force_refresh,
            now=cycle_timestamp,
        )
        universe = tuple(scan_result.shortlisted_symbols)

        self.repository.append_log_event(
            level="INFO",
            logger_name=LOGGER.name,
            event="worker_universe_scan",
            payload={
                "worker_name": self.settings.worker_name,
                "cycle_key": heartbeat_cycle_key,
                **scan_result.as_dict(),
            },
        )
        LOGGER.info(
            "worker_universe_scan cycle_key=%s mode=%s scanned=%d shortlisted=%d",
            heartbeat_cycle_key,
            scan_result.mode,
            len(scan_result.scanned_symbols),
            len(scan_result.shortlisted_symbols),
        )
        for symbol, reasons in sorted(scan_result.filtered_out_reasons.items()):
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="worker_symbol_filtered",
                payload={
                    "worker_name": self.settings.worker_name,
                    "cycle_key": heartbeat_cycle_key,
                    "symbol": symbol,
                    "reasons": list(reasons),
                },
            )

        if not universe:
            self.repository.record_worker_heartbeat(
                worker_name=self.settings.worker_name,
                status="idle",
                last_cycle_key=heartbeat_cycle_key,
                message="no_shortlisted_symbols",
            )
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="worker_cycle_skipped",
                payload={
                    "cycle_key": heartbeat_cycle_key,
                    "reason": "no_shortlisted_symbols",
                    "universe_mode": self.settings.worker_universe_mode,
                    "configured_universe": list(configured_universe),
                    "scanned_symbols": list(scan_result.scanned_symbols),
                    "filtered_out_reasons": {
                        symbol: list(reasons)
                        for symbol, reasons in scan_result.filtered_out_reasons.items()
                    },
                },
            )
            return

        service_key = f"worker:{self.settings.worker_name}"
        summaries: list[SymbolCycleSummary] = []
        for symbol in universe:
            summaries.append(
                self._run_symbol_cycle(
                    symbol=symbol,
                    cycle_timestamp=cycle_timestamp,
                    service_key=service_key,
                    executor=executor,
                    analytics=performance_snapshot,
                    symbol_strategy_locks=symbol_strategy_locks,
                    scan_result=scan_result,
                )
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

        self._release_stale_locks(
            executor=executor,
            symbol_strategy_locks=symbol_strategy_locks,
        )

        if executor.kill_switch_enabled:
            self.repository.set_global_kill_switch(
                True,
                reason="worker_runtime_kill_switch",
            )

        error_count = sum(1 for row in summaries if row.status == "failed")
        duplicate_count = sum(1 for row in summaries if row.status == "duplicate")
        if error_count > 0:
            status = "error"
            message = f"errors={error_count} duplicates={duplicate_count}"
        elif duplicate_count == len(summaries):
            status = "duplicate"
            message = f"all_duplicates={duplicate_count}"
        else:
            status = "ok"
            selected = [
                f"{row.symbol}:{row.selected_strategy or 'none'}"
                for row in summaries
            ]
            message = ",".join(selected)

        selected_summary = next(
            (row for row in summaries if row.selected_strategy is not None),
            None,
        )
        last_no_trade_reason = next(
            (row.no_trade_reason for row in summaries if row.no_trade_reason),
            None,
        )
        LOGGER.info(
            "worker_cycle_summary cycle_key=%s dry_run=%s scanned=%s shortlisted=%s selected_symbol=%s selected_strategy=%s no_trade_reason=%s",
            heartbeat_cycle_key,
            self.settings.worker_dry_run,
            ",".join(scan_result.scanned_symbols),
            ",".join(scan_result.shortlisted_symbols),
            selected_summary.symbol if selected_summary is not None else "none",
            selected_summary.selected_strategy if selected_summary is not None else "none",
            last_no_trade_reason or "none",
        )
        self.repository.append_log_event(
            level="INFO",
            logger_name=LOGGER.name,
            event="worker_cycle_summary",
            payload={
                "cycle_key": heartbeat_cycle_key,
                "worker_name": self.settings.worker_name,
                "dry_run": self.settings.worker_dry_run,
                "scanned_symbols": list(scan_result.scanned_symbols),
                "shortlisted_symbols": list(scan_result.shortlisted_symbols),
                "filtered_out_reasons": {
                    symbol: list(reasons)
                    for symbol, reasons in scan_result.filtered_out_reasons.items()
                },
                "selected_symbol": (
                    selected_summary.symbol if selected_summary is not None else None
                ),
                "selected_strategy": (
                    selected_summary.selected_strategy if selected_summary is not None else None
                ),
                "last_no_trade_reason": last_no_trade_reason,
            },
        )

        self.repository.record_worker_heartbeat(
            worker_name=self.settings.worker_name,
            status=status,
            last_cycle_key=heartbeat_cycle_key,
            message=message[:250],
        )

    def _run_symbol_cycle(
        self,
        symbol: str,
        cycle_timestamp: pd.Timestamp,
        service_key: str,
        executor: PaperTradingExecutor,
        analytics: PerformanceAnalyticsSnapshot,
        symbol_strategy_locks: dict[str, str],
        scan_result: UniverseScanResult,
    ) -> SymbolCycleSummary:
        """Execute one symbol cycle and return a structured summary."""
        cycle_key = self._cycle_key(symbol=symbol, timestamp=cycle_timestamp)
        run_id = f"worker-{uuid4().hex}"
        symbol_snapshot = scan_result.snapshots_by_symbol.get(symbol)

        if not self.repository.start_run(
            run_id=run_id,
            service=service_key,
            cycle_key=cycle_key,
            symbol=symbol,
            timeframe=self.settings.worker_timeframe,
            strategy="strategy_selector",
            details={
                "source": "worker_cycle",
                "universe_mode": self.settings.worker_universe_mode,
                "configured_universe": list(self.settings.worker_symbols),
                "scanned_symbols": list(scan_result.scanned_symbols),
                "shortlisted_symbols": list(scan_result.shortlisted_symbols),
                "symbol_snapshot": (
                    symbol_snapshot.as_dict()
                    if symbol_snapshot is not None
                    else None
                ),
            },
        ):
            LOGGER.info(
                "worker_symbol_cycle_skipped reason=duplicate_cycle symbol=%s cycle_key=%s",
                symbol,
                cycle_key,
            )
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="worker_symbol_cycle_skipped",
                payload={
                    "cycle_key": cycle_key,
                    "symbol": symbol,
                    "reason": "duplicate_cycle",
                },
            )
            return SymbolCycleSummary(
                symbol=symbol,
                run_id=None,
                status="duplicate",
                action="duplicate_cycle",
                selected_strategy=None,
                active_strategy=symbol_strategy_locks.get(symbol),
                order_status=None,
                no_trade_reason="duplicate_cycle",
                rejection_reasons=(),
            )

        start_run(run_id=run_id)
        try:
            data = self.loader.load(
                symbol=symbol,
                timeframe=self.settings.worker_timeframe,
                force_refresh=False,
            )
            latest_price = float(data["close"].iloc[-1])
            latest_timestamp = pd.Timestamp(data.index[-1])

            regime = classify_regime(data)
            LOGGER.info(
                "regime_classified cycle_key=%s symbol=%s regime=%s ma_slope=%.6f price_vs_ma=%.6f atr_pct=%.6f persistence=%.6f",
                cycle_key,
                symbol,
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
                    "symbol": symbol,
                    "regime": regime.state,
                    **regime.as_signals(),
                },
            )

            locked_strategy = None
            if not self.settings.worker_allow_multi_strategy_per_symbol:
                locked_strategy = symbol_strategy_locks.get(symbol)

            candidates = self._build_strategy_candidates(
                data=data,
                analytics=analytics,
                symbol=symbol,
                locked_strategy=locked_strategy,
            )
            selection_state = self._build_global_selection_state(
                executor=executor,
                latest_price=latest_price,
                symbol=symbol,
            )
            decision = self.selector.select(
                regime=regime,
                candidates=candidates,
                global_state=selection_state,
            )

            self._log_selection_decision(
                run_id=run_id,
                cycle_key=cycle_key,
                symbol=symbol,
                decision=decision,
            )

            selected_signal = 0.0
            if decision.selected_strategy is not None:
                selected_entry = next(
                    (item for item in decision.candidates if item.strategy == decision.selected_strategy),
                    None,
                )
                if selected_entry is not None:
                    selected_signal = float(selected_entry.signal)

            current_position = executor.positions.get(symbol)
            order = self._build_order(
                symbol=symbol,
                selected_strategy=decision.selected_strategy,
                selected_signal=selected_signal,
                latest_price=latest_price,
                latest_timestamp=latest_timestamp,
                current_position=current_position,
                sizing_multiplier=decision.sizing_multiplier,
            )

            if order is None:
                no_trade_reason = self._determine_no_trade_reason(
                    decision=decision,
                    selected_signal=selected_signal,
                    current_position=current_position,
                )
                self._sync_lock_on_no_order(
                    symbol=symbol,
                    current_position=executor.positions.get(symbol),
                    selected_strategy=decision.selected_strategy,
                    run_id=run_id,
                    symbol_strategy_locks=symbol_strategy_locks,
                )
                self.repository.append_log_event(
                    level="INFO",
                    logger_name=LOGGER.name,
                    event="worker_no_order",
                    run_id=run_id,
                    payload={
                        "cycle_key": cycle_key,
                        "symbol": symbol,
                        "no_trade_reason": no_trade_reason,
                        "selection": decision.as_dict(),
                    },
                )
                self.repository.finish_run(
                    run_id=run_id,
                    status="completed",
                    details={
                        "selection": decision.as_dict(),
                        "action": "no_order",
                        "no_trade_reason": no_trade_reason,
                        "active_strategy": symbol_strategy_locks.get(symbol),
                    },
                )
                return SymbolCycleSummary(
                    symbol=symbol,
                    run_id=run_id,
                    status="completed",
                    action="no_order",
                    selected_strategy=decision.selected_strategy,
                    active_strategy=symbol_strategy_locks.get(symbol),
                    order_status=None,
                    no_trade_reason=no_trade_reason,
                    rejection_reasons=(),
                )

            if self.settings.worker_dry_run:
                LOGGER.info(
                    "worker_dry_run_order_skipped cycle_key=%s symbol=%s side=%s qty=%.6f price=%.6f selected_strategy=%s",
                    cycle_key,
                    symbol,
                    order.side.upper(),
                    order.quantity,
                    order.price,
                    decision.selected_strategy or "none",
                )
                self.repository.append_log_event(
                    level="INFO",
                    logger_name=LOGGER.name,
                    event="worker_dry_run_order_skipped",
                    run_id=run_id,
                    payload={
                        "cycle_key": cycle_key,
                        "symbol": symbol,
                        "order": {
                            "symbol": order.symbol,
                            "side": order.side.upper(),
                            "quantity": float(order.quantity),
                            "price": float(order.price),
                        },
                        "selection": decision.as_dict(),
                        "no_trade_reason": "dry_run_enabled",
                    },
                )
                self.repository.finish_run(
                    run_id=run_id,
                    status="completed",
                    details={
                        "selection": decision.as_dict(),
                        "action": "dry_run_order_skipped",
                        "dry_run": True,
                        "no_trade_reason": "dry_run_enabled",
                        "active_strategy": symbol_strategy_locks.get(symbol),
                    },
                )
                return SymbolCycleSummary(
                    symbol=symbol,
                    run_id=run_id,
                    status="completed",
                    action="dry_run_order_skipped",
                    selected_strategy=decision.selected_strategy,
                    active_strategy=symbol_strategy_locks.get(symbol),
                    order_status=None,
                    no_trade_reason="dry_run_enabled",
                    rejection_reasons=(),
                )

            dedupe_key = self.repository.compute_order_dedupe_key(cycle_key, order)
            if self.repository.order_exists_by_dedupe_key(dedupe_key):
                self.repository.append_log_event(
                    level="INFO",
                    logger_name=LOGGER.name,
                    event="worker_duplicate_order_skipped",
                    run_id=run_id,
                    payload={
                        "cycle_key": cycle_key,
                        "symbol": symbol,
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
                        "no_trade_reason": "duplicate_order_skipped",
                        "active_strategy": symbol_strategy_locks.get(symbol),
                    },
                )
                return SymbolCycleSummary(
                    symbol=symbol,
                    run_id=run_id,
                    status="duplicate",
                    action="duplicate_order_skipped",
                    selected_strategy=decision.selected_strategy,
                    active_strategy=symbol_strategy_locks.get(symbol),
                    order_status=None,
                    no_trade_reason="duplicate_order_skipped",
                    rejection_reasons=(),
                )

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

            self._sync_lock_after_execution(
                symbol=symbol,
                decision=decision,
                order=order,
                result_status=result.status,
                executor=executor,
                run_id=run_id,
                symbol_strategy_locks=symbol_strategy_locks,
            )

            self.repository.append_log_event(
                level="INFO" if result.status == "FILLED" else "WARNING",
                logger_name=LOGGER.name,
                event="worker_order_processed",
                run_id=run_id,
                payload={
                    "cycle_key": cycle_key,
                    "symbol": symbol,
                    "order_id": result.order_id,
                    "status": result.status,
                    "rejection_reasons": list(result.rejection_reasons),
                    "selection": decision.as_dict(),
                    "active_strategy": symbol_strategy_locks.get(symbol),
                },
            )

            self.repository.finish_run(
                run_id=run_id,
                status="completed",
                details={
                    "selection": decision.as_dict(),
                    "action": "order_processed",
                    "order_id": result.order_id,
                    "order_status": result.status,
                    "rejection_reasons": list(result.rejection_reasons),
                    "no_trade_reason": (
                        "order_rejected:" + ",".join(result.rejection_reasons)
                        if result.status != "FILLED" and result.rejection_reasons
                        else None
                    ),
                    "active_strategy": symbol_strategy_locks.get(symbol),
                },
            )
            return SymbolCycleSummary(
                symbol=symbol,
                run_id=run_id,
                status="completed",
                action="order_processed",
                selected_strategy=decision.selected_strategy,
                active_strategy=symbol_strategy_locks.get(symbol),
                order_status=result.status,
                no_trade_reason=(
                    "order_rejected:" + ",".join(result.rejection_reasons)
                    if result.status != "FILLED" and result.rejection_reasons
                    else None
                ),
                rejection_reasons=tuple(result.rejection_reasons),
            )
        except Exception as exc:
            LOGGER.exception(
                "worker_symbol_cycle_failed symbol=%s cycle_key=%s error=%s",
                symbol,
                cycle_key,
                exc,
            )
            self.repository.finish_run(
                run_id=run_id,
                status="failed",
                error_message=str(exc),
                details={
                    "action": "cycle_failed",
                    "symbol": symbol,
                },
            )
            self.repository.append_log_event(
                level="ERROR",
                logger_name=LOGGER.name,
                event="worker_symbol_cycle_failed",
                run_id=run_id,
                payload={
                    "cycle_key": cycle_key,
                    "symbol": symbol,
                    "error": str(exc),
                },
            )
            return SymbolCycleSummary(
                symbol=symbol,
                run_id=run_id,
                status="failed",
                action="cycle_failed",
                selected_strategy=None,
                active_strategy=symbol_strategy_locks.get(symbol),
                order_status=None,
                no_trade_reason="cycle_failed",
                rejection_reasons=(),
            )
        finally:
            clear_run()

    def _sync_lock_on_no_order(
        self,
        symbol: str,
        current_position: Position | None,
        selected_strategy: str | None,
        run_id: str,
        symbol_strategy_locks: dict[str, str],
    ) -> None:
        """Maintain symbol strategy lock state when no order was submitted."""
        if self.settings.worker_allow_multi_strategy_per_symbol:
            return

        current_qty = 0.0 if current_position is None else float(current_position.quantity)
        if current_qty <= EPSILON:
            if symbol in symbol_strategy_locks:
                self.repository.release_symbol_strategy_lock(symbol)
                symbol_strategy_locks.pop(symbol, None)
            return

        if symbol not in symbol_strategy_locks and selected_strategy is not None:
            self.repository.upsert_symbol_strategy_lock(
                symbol=symbol,
                strategy=selected_strategy,
                run_id=run_id,
                reason="position_open",
            )
            symbol_strategy_locks[symbol] = selected_strategy

    def _sync_lock_after_execution(
        self,
        symbol: str,
        decision: SelectionDecision,
        order: Order,
        result_status: str,
        executor: PaperTradingExecutor,
        run_id: str,
        symbol_strategy_locks: dict[str, str],
    ) -> None:
        """Maintain symbol strategy lock state after order processing."""
        if self.settings.worker_allow_multi_strategy_per_symbol or result_status != "FILLED":
            return

        if order.side.upper() == "BUY" and decision.selected_strategy is not None:
            self.repository.upsert_symbol_strategy_lock(
                symbol=symbol,
                strategy=decision.selected_strategy,
                run_id=run_id,
                reason="buy_fill",
            )
            symbol_strategy_locks[symbol] = decision.selected_strategy
            return

        position = executor.positions.get(symbol)
        if order.side.upper() == "SELL" and (
            position is None or float(position.quantity) <= EPSILON
        ):
            self.repository.release_symbol_strategy_lock(symbol)
            symbol_strategy_locks.pop(symbol, None)

    def _release_stale_locks(
        self,
        executor: PaperTradingExecutor,
        symbol_strategy_locks: dict[str, str],
    ) -> None:
        """Release any lock whose symbol no longer has an open position."""
        stale_symbols: list[str] = []
        for symbol in symbol_strategy_locks:
            position = executor.positions.get(symbol)
            if position is None or float(position.quantity) <= EPSILON:
                stale_symbols.append(symbol)

        for symbol in stale_symbols:
            self.repository.release_symbol_strategy_lock(symbol)
            symbol_strategy_locks.pop(symbol, None)

    def _build_performance_snapshot(
        self,
        snapshot: PortfolioSnapshot,
    ) -> PerformanceAnalyticsSnapshot:
        """Build analytics snapshot from persisted fills/runs for selection + API parity."""
        fills = self.repository.recent_fills(limit=5000, run_service_prefix="worker:")
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
        symbol: str,
        locked_strategy: str | None,
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

            external_reasons: tuple[str, ...] = ()
            if (
                locked_strategy is not None
                and strategy_name != locked_strategy
                and not self.settings.worker_allow_multi_strategy_per_symbol
            ):
                external_reasons = (f"symbol_locked_by_active_strategy:{locked_strategy}",)

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
                    external_reasons=external_reasons,
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
        symbol: str,
    ) -> GlobalSelectionState:
        """Compute global gating state for deterministic eligibility checks."""
        current_equity = executor.current_equity()
        required_notional = float(self.settings.worker_order_quantity * latest_price)
        max_position_notional = float(self.settings.max_position_size * current_equity)
        available_notional = float(min(self.settings.max_notional_per_trade, max_position_notional))

        active_positions = sum(1 for item in executor.positions.values() if item.quantity > EPSILON)
        has_symbol_position = (
            executor.positions.get(symbol) is not None
            and float(executor.positions[symbol].quantity) > EPSILON
        )
        max_positions_breached = (
            active_positions >= self.settings.max_open_positions and not has_symbol_position
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
        symbol: str,
        decision: SelectionDecision,
    ) -> None:
        """Emit structured selection logs for auditability and debugging."""
        for candidate in decision.candidates:
            LOGGER.info(
                "strategy_eligibility_decision cycle_key=%s symbol=%s strategy=%s eligible=%s reasons=%s",
                cycle_key,
                symbol,
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
                    "symbol": symbol,
                    "strategy": candidate.strategy,
                    "eligible": candidate.eligible,
                    "reasons": list(candidate.reasons),
                },
            )

            LOGGER.info(
                "strategy_score cycle_key=%s symbol=%s strategy=%s score=%.6f expectancy=%.6f sharpe=%.6f win_rate=%.6f regime_fit=%.6f drawdown_penalty=%.6f",
                cycle_key,
                symbol,
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
                    "symbol": symbol,
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
                        "symbol": symbol,
                        "strategy": candidate.strategy,
                        "reasons": list(candidate.reasons),
                    },
                )

        LOGGER.info(
            "strategy_selected cycle_key=%s symbol=%s strategy=%s score=%.6f",
            cycle_key,
            symbol,
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
                "symbol": symbol,
                "selected_strategy": decision.selected_strategy,
                "selected_score": float(decision.selected_score),
                "regime": decision.regime,
            },
        )

        LOGGER.info(
            "sizing_decision cycle_key=%s symbol=%s strategy=%s sizing_multiplier=%.4f allocation_fraction=%.4f",
            cycle_key,
            symbol,
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
                "symbol": symbol,
                "selected_strategy": decision.selected_strategy,
                "sizing_multiplier": float(decision.sizing_multiplier),
                "allocation_fraction": float(decision.allocation_fraction),
            },
        )

    def _build_order(
        self,
        symbol: str,
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
                symbol=symbol,
                side="BUY",
                quantity=quantity,
                price=latest_price,
                timestamp=latest_timestamp,
            )

        if (selected_strategy is None or selected_signal <= EPSILON) and current_qty > EPSILON:
            return Order(
                symbol=symbol,
                side="SELL",
                quantity=current_qty,
                price=latest_price,
                timestamp=latest_timestamp,
            )
        return None

    def _determine_no_trade_reason(
        self,
        decision: SelectionDecision,
        selected_signal: float,
        current_position: Position | None,
    ) -> str:
        """Derive a deterministic no-trade reason for cycle-level observability."""
        current_qty = 0.0 if current_position is None else float(current_position.quantity)

        if decision.selected_strategy is None:
            if decision.candidates:
                top = decision.candidates[0]
                if top.reasons:
                    return f"no_eligible_strategy:{top.reasons[0]}"
            return "no_eligible_strategy"

        if selected_signal <= EPSILON and current_qty <= EPSILON:
            return "selected_signal_not_actionable"
        if selected_signal > EPSILON and current_qty > EPSILON:
            return "position_already_open"
        if decision.sizing_multiplier <= EPSILON:
            return "sizing_multiplier_zero"
        return "no_order_condition_not_met"

    def _heartbeat_cycle_key(self, timestamp: pd.Timestamp) -> str:
        """Derive a cross-universe cycle key for worker heartbeat updates."""
        if self.settings.worker_timeframe.endswith("d"):
            return f"{self.settings.worker_timeframe}:{timestamp.strftime('%Y-%m-%d')}"
        return f"{self.settings.worker_timeframe}:{timestamp.floor('min').strftime('%Y-%m-%dT%H:%M')}"

    def _cycle_key(self, symbol: str, timestamp: pd.Timestamp) -> str:
        """Derive per-symbol cycle key for idempotent symbol execution."""
        if self.settings.worker_timeframe.endswith("d"):
            return f"{symbol}:{self.settings.worker_timeframe}:{timestamp.strftime('%Y-%m-%d')}"
        return (
            f"{symbol}:{self.settings.worker_timeframe}:"
            f"{timestamp.floor('min').strftime('%Y-%m-%dT%H:%M')}"
        )
