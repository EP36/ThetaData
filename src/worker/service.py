"""Background worker for unattended paper-trading execution loops."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import logging
from pathlib import Path
import time
from typing import Any, cast
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
from src.trading import (
    GatedTradeIntent,
    MarketRegimeEvaluation,
    PositionSizingConfig,
    RiskPolicyConfig,
    StrategyGateConfig,
    TradeIntent,
    TradingRiskState,
    calculate_position_size,
    evaluate_risk_policy,
    gate_trade_intent,
    get_market_regime,
    normalize_strategy_id,
)
from src.worker.universe import (
    UniverseMode,
    UniverseScanResult,
    UniverseScanner,
    UniverseScannerConfig,
)

LOGGER = logging.getLogger("theta.worker.service")
EPSILON = 1e-12
STRATEGY_LOGIC_REASONS = {
    "strategy_disabled",
    "required_market_data_missing",
    "insufficient_recent_trades",
    "recent_drawdown_exceeded",
    "recent_expectancy_below_threshold",
    "no_active_signal",
    "regime_incompatible",
    "score_below_threshold",
}
GLOBAL_GATE_REASONS = {
    "kill_switch_enabled",
    "paper_trading_disabled",
    "worker_trading_disabled",
    "insufficient_risk_budget",
    "max_open_positions_breached",
}


def _build_loader(cache_dir: str) -> HistoricalDataLoader:
    """Create worker loader using configured provider abstractions."""
    provider = make_market_data_provider_from_env()
    cache = DataCache(root_dir=Path(cache_dir))
    return HistoricalDataLoader(provider=provider, cache=cache)


def _coerce_float(value: object) -> float | None:
    """Return a float when the value is numeric-like."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


@dataclass(frozen=True, slots=True)
class OrderPlanningResult:
    """Outcome from entry gating/sizing/order preparation."""

    order: Order | None
    no_trade_reason: str | None = None
    rejection_reasons: tuple[str, ...] = ()


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
    _execution_timeframe: str = field(init=False, default="1d", repr=False)
    _worker_service_key: str = field(init=False, default="", repr=False)
    _last_universe_cycle_key: str | None = field(init=False, default=None, repr=False)
    _registered_cycle_count: int = field(init=False, default=0, repr=False)

    def __post_init__(self) -> None:
        self._execution_timeframe = self.settings.worker_timeframe.strip()
        self._worker_service_key = f"worker:{self.settings.worker_name}"
        self.loader = _build_loader(cache_dir=self.settings.cache_dir)
        self.universe_scanner = UniverseScanner(
            loader=self.loader,
            config=UniverseScannerConfig(
                timeframe=self._execution_timeframe,
                max_candidates=self.settings.worker_max_candidates,
                min_price=self.settings.min_price,
                min_average_volume=self.settings.min_avg_volume,
                min_relative_volume=self.settings.min_relative_volume,
                max_spread_pct=self.settings.max_spread_pct,
                trading_start=self.settings.trading_start,
                trading_end=self.settings.trading_end,
                allow_after_hours=self.settings.allow_after_hours,
                only_open_new_positions_during_market_hours=(
                    self.settings.only_open_new_positions_during_market_hours
                ),
                stale_market_data_grace_minutes=(
                    self.settings.worker_stale_market_data_grace_minutes
                ),
                stale_market_data_interval_multiplier=(
                    self.settings.worker_stale_market_data_interval_multiplier
                ),
            ),
        )
        self.selector = StrategySelector(
            config=SelectionConfig(
                min_recent_trades=self.settings.selection_min_recent_trades,
            )
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
            "worker_start service=%s worker_name=%s timeframe=%s paper_trading=%s worker_enable_trading=%s worker_dry_run=%s poll_seconds=%d universe_mode=%s universe=%s selection_min_recent_trades=%d startup_warmup_cycles=%d",
            self.settings.service_name,
            self.settings.worker_name,
            self._execution_timeframe,
            self.settings.paper_trading_enabled,
            self.settings.worker_enable_trading,
            self.settings.worker_dry_run,
            self.settings.worker_poll_seconds,
            self.settings.worker_universe_mode,
            ",".join(self.settings.worker_symbols),
            self.settings.selection_min_recent_trades,
            self.settings.worker_startup_warmup_cycles,
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
                "timeframe": self._execution_timeframe,
                "universe_mode": self.settings.worker_universe_mode,
                "universe": list(self.settings.worker_symbols),
                "worker_max_candidates": self.settings.worker_max_candidates,
                "selection_min_recent_trades": self.settings.selection_min_recent_trades,
                "worker_startup_warmup_cycles": self.settings.worker_startup_warmup_cycles,
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

        if self._last_universe_cycle_key == heartbeat_cycle_key:
            LOGGER.info(
                "worker_universe_cycle_duplicate_detected cycle_key=%s reason=same_poll_bucket duplicate_validity=valid",
                heartbeat_cycle_key,
            )
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="worker_universe_cycle_duplicate_detected",
                payload={
                    "cycle_key": heartbeat_cycle_key,
                    "reason": "same_poll_bucket",
                    "duplicate_validity": "valid",
                    "worker_name": self.settings.worker_name,
                    "poll_seconds": self.settings.worker_poll_seconds,
                },
            )
            self.repository.record_worker_heartbeat(
                worker_name=self.settings.worker_name,
                status="duplicate",
                last_cycle_key=heartbeat_cycle_key,
                message="duplicate_universe_cycle_key_same_poll_bucket",
            )
            return

        self._last_universe_cycle_key = heartbeat_cycle_key
        self._registered_cycle_count += 1
        warmup_active = self._registered_cycle_count <= self.settings.worker_startup_warmup_cycles
        effective_min_recent_trades = (
            0 if warmup_active else self.settings.selection_min_recent_trades
        )
        LOGGER.info(
            "worker_universe_cycle_key_registered cycle_key=%s timeframe=%s poll_seconds=%d cycle_number=%d warmup_active=%s effective_min_recent_trades=%d",
            heartbeat_cycle_key,
            self._execution_timeframe,
            self.settings.worker_poll_seconds,
            self._registered_cycle_count,
            warmup_active,
            effective_min_recent_trades,
        )
        self.repository.append_log_event(
            level="INFO",
            logger_name=LOGGER.name,
            event="worker_universe_cycle_key_registered",
            payload={
                "cycle_key": heartbeat_cycle_key,
                "worker_name": self.settings.worker_name,
                "timeframe": self._execution_timeframe,
                "poll_seconds": self.settings.worker_poll_seconds,
                "cycle_number": self._registered_cycle_count,
                "warmup_active": warmup_active,
                "effective_min_recent_trades": effective_min_recent_trades,
            },
        )
        self.repository.append_log_event(
            level="INFO",
            logger_name=LOGGER.name,
            event="worker_warmup_state",
            payload={
                "cycle_key": heartbeat_cycle_key,
                "worker_name": self.settings.worker_name,
                "cycle_number": self._registered_cycle_count,
                "warmup_active": warmup_active,
                "startup_warmup_cycles": self.settings.worker_startup_warmup_cycles,
                "configured_min_recent_trades": self.settings.selection_min_recent_trades,
                "effective_min_recent_trades": effective_min_recent_trades,
            },
        )

        effective_max_open_positions = self._effective_max_open_positions()
        effective_max_gross_exposure = self._effective_max_gross_exposure()
        risk_manager = RiskManager(
            max_position_size=self.settings.max_position_size,
            max_daily_loss=self.settings.max_daily_loss,
            max_gross_exposure=effective_max_gross_exposure,
            max_open_positions=effective_max_open_positions,
            trading_start=self.settings.trading_start,
            trading_end=self.settings.trading_end,
            allow_after_hours=self.settings.allow_after_hours,
            default_stop_loss_pct=self.settings.default_stop_loss_pct_for_sizing,
        )
        executor = PaperTradingExecutor(
            starting_cash=self.settings.initial_capital,
            risk_manager=risk_manager,
            paper_trading_enabled=(
                self.settings.paper_trading_enabled and not self.settings.worker_dry_run
            ),
            max_notional_per_trade=self.settings.max_notional_per_trade,
            max_open_positions=effective_max_open_positions,
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
        rejection_reason_counts = scan_result.filtered_out_reason_counts()
        rejection_reason_group_counts = scan_result.filtered_out_reason_group_counts()
        rejection_reason_groups = scan_result.filtered_out_reason_groups()

        self.repository.append_log_event(
            level="INFO",
            logger_name=LOGGER.name,
            event="worker_universe_scan",
            payload={
                "worker_name": self.settings.worker_name,
                "cycle_key": heartbeat_cycle_key,
                "timeframe": self._execution_timeframe,
                "warmup_active": warmup_active,
                "effective_min_recent_trades": effective_min_recent_trades,
                "filtered_out_reason_counts": rejection_reason_counts,
                "filtered_out_reason_group_counts": rejection_reason_group_counts,
                **scan_result.as_dict(),
            },
        )
        LOGGER.info(
            "worker_universe_scan cycle_key=%s timeframe=%s mode=%s scanned=%d shortlisted=%d rejected=%d warmup_active=%s rejection_counts=%s",
            heartbeat_cycle_key,
            self._execution_timeframe,
            scan_result.mode,
            len(scan_result.scanned_symbols),
            len(scan_result.shortlisted_symbols),
            len(scan_result.filtered_out_reasons),
            warmup_active,
            ",".join(
                f"{reason}:{count}"
                for reason, count in rejection_reason_counts.items()
            )
            or "none",
        )
        for symbol, reasons in sorted(scan_result.filtered_out_reasons.items()):
            rejection_payload = scan_result.symbol_rejection_payload(symbol)
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="worker_symbol_filtered",
                payload={
                    "worker_name": self.settings.worker_name,
                    "cycle_key": heartbeat_cycle_key,
                    "timeframe": self._execution_timeframe,
                    "symbol": symbol,
                    "reasons": list(reasons),
                    "rejection_reasons": list(reasons),
                    "reason_groups": rejection_payload.get("reason_groups", []),
                    "pipeline_stage": "universe_scan",
                    "latest_bar_timestamp": rejection_payload.get("latest_bar_timestamp"),
                    "latest_bar_age_minutes": rejection_payload.get("latest_bar_age_minutes"),
                    "min_avg_volume_threshold": rejection_payload.get(
                        "min_avg_volume_threshold"
                    ),
                    "actual_avg_volume": rejection_payload.get("actual_avg_volume"),
                    "min_relative_volume_threshold": rejection_payload.get(
                        "min_relative_volume_threshold"
                    ),
                    "actual_relative_volume": rejection_payload.get(
                        "actual_relative_volume"
                    ),
                    "market_session_state": rejection_payload.get(
                        "market_session_state"
                    ),
                    "freshness_rejection_reason": rejection_payload.get(
                        "freshness_rejection_reason"
                    ),
                },
            )
        if scan_result.filtered_out_reasons:
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="worker_universe_rejection_summary",
                payload={
                    "worker_name": self.settings.worker_name,
                    "cycle_key": heartbeat_cycle_key,
                    "timeframe": self._execution_timeframe,
                    "rejected_symbols": sorted(scan_result.filtered_out_reasons),
                    "rejection_reason_counts": rejection_reason_counts,
                    "rejection_reason_group_counts": rejection_reason_group_counts,
                },
            )

        if not universe:
            LOGGER.info(
                "worker_no_shortlist cycle_key=%s timeframe=%s scanned=%d reason=no_shortlisted_symbols rejection_counts=%s",
                heartbeat_cycle_key,
                self._execution_timeframe,
                len(scan_result.scanned_symbols),
                ",".join(
                    f"{reason}:{count}"
                    for reason, count in rejection_reason_counts.items()
                )
                or "none",
            )
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
                    "timeframe": self._execution_timeframe,
                    "universe_mode": self.settings.worker_universe_mode,
                    "configured_universe": list(configured_universe),
                    "scanned_symbols": list(scan_result.scanned_symbols),
                    "filtered_out_reasons": {
                        symbol: list(reasons)
                        for symbol, reasons in scan_result.filtered_out_reasons.items()
                    },
                    "filtered_out_reason_groups": rejection_reason_groups,
                    "filtered_out_reason_counts": rejection_reason_counts,
                    "filtered_out_reason_group_counts": rejection_reason_group_counts,
                },
            )
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="worker_no_shortlist",
                payload={
                    "cycle_key": heartbeat_cycle_key,
                    "worker_name": self.settings.worker_name,
                    "timeframe": self._execution_timeframe,
                    "scanned_symbols": list(scan_result.scanned_symbols),
                    "filtered_out_reasons": {
                        symbol: list(reasons)
                        for symbol, reasons in scan_result.filtered_out_reasons.items()
                    },
                    "filtered_out_reason_groups": rejection_reason_groups,
                    "filtered_out_reason_counts": rejection_reason_counts,
                    "filtered_out_reason_group_counts": rejection_reason_group_counts,
                    "warmup_active": warmup_active,
                    "effective_min_recent_trades": effective_min_recent_trades,
                },
            )
            return

        service_key = self._worker_service_key
        summaries: list[SymbolCycleSummary] = []
        for symbol in universe:
            summaries.append(
                self._run_symbol_cycle(
                    symbol=symbol,
                    heartbeat_cycle_key=heartbeat_cycle_key,
                    warmup_active=warmup_active,
                    effective_min_recent_trades=effective_min_recent_trades,
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
            "worker_cycle_summary cycle_key=%s timeframe=%s dry_run=%s warmup_active=%s effective_min_recent_trades=%d scanned=%s shortlisted=%s selected_symbol=%s selected_strategy=%s no_trade_reason=%s",
            heartbeat_cycle_key,
            self._execution_timeframe,
            self.settings.worker_dry_run,
            warmup_active,
            effective_min_recent_trades,
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
                "timeframe": self._execution_timeframe,
                "dry_run": self.settings.worker_dry_run,
                "warmup_active": warmup_active,
                "effective_min_recent_trades": effective_min_recent_trades,
                "scanned_symbols": list(scan_result.scanned_symbols),
                "shortlisted_symbols": list(scan_result.shortlisted_symbols),
                "filtered_out_reasons": {
                    symbol: list(reasons)
                    for symbol, reasons in scan_result.filtered_out_reasons.items()
                },
                "filtered_out_reason_groups": rejection_reason_groups,
                "filtered_out_reason_counts": rejection_reason_counts,
                "filtered_out_reason_group_counts": rejection_reason_group_counts,
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
        heartbeat_cycle_key: str,
        warmup_active: bool,
        effective_min_recent_trades: int,
        service_key: str,
        executor: PaperTradingExecutor,
        analytics: PerformanceAnalyticsSnapshot,
        symbol_strategy_locks: dict[str, str],
        scan_result: UniverseScanResult,
    ) -> SymbolCycleSummary:
        """Execute one symbol cycle and return a structured summary."""
        cycle_key = self._cycle_key(
            symbol=symbol,
            heartbeat_cycle_key=heartbeat_cycle_key,
        )
        run_id = f"worker-{uuid4().hex}"
        symbol_snapshot = scan_result.snapshots_by_symbol.get(symbol)

        if not self.repository.start_run(
            run_id=run_id,
            service=service_key,
            cycle_key=cycle_key,
            symbol=symbol,
            timeframe=self._execution_timeframe,
            strategy="strategy_selector",
            details={
                "source": "worker_cycle",
                "heartbeat_cycle_key": heartbeat_cycle_key,
                "timeframe": self._execution_timeframe,
                "warmup_active": warmup_active,
                "effective_min_recent_trades": effective_min_recent_trades,
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
            existing_run = self.repository.get_run_by_service_cycle_key(
                service=service_key,
                cycle_key=cycle_key,
            )
            duplicate_validity = "unknown"
            duplicate_reason = "existing_run_not_found"
            if existing_run is not None:
                details_map = dict(existing_run.get("details") or {})
                existing_heartbeat = str(details_map.get("heartbeat_cycle_key") or "").strip()
                if existing_heartbeat == heartbeat_cycle_key:
                    duplicate_validity = "valid"
                    duplicate_reason = "same_worker_poll_cycle"
                elif existing_heartbeat:
                    duplicate_validity = "invalid"
                    duplicate_reason = "stale_cycle_key_collision"
                else:
                    duplicate_validity = "unknown"
                    duplicate_reason = "existing_run_missing_heartbeat_cycle_key"

            LOGGER.info(
                "worker_symbol_cycle_duplicate_detected symbol=%s cycle_key=%s duplicate_validity=%s duplicate_reason=%s",
                symbol,
                cycle_key,
                duplicate_validity,
                duplicate_reason,
            )
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="worker_symbol_cycle_duplicate_detected",
                payload={
                    "cycle_key": cycle_key,
                    "heartbeat_cycle_key": heartbeat_cycle_key,
                    "symbol": symbol,
                    "reason": "duplicate_cycle",
                    "duplicate_validity": duplicate_validity,
                    "duplicate_reason": duplicate_reason,
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

        LOGGER.info(
            "worker_symbol_cycle_key_registered symbol=%s cycle_key=%s heartbeat_cycle_key=%s",
            symbol,
            cycle_key,
            heartbeat_cycle_key,
        )
        self.repository.append_log_event(
            level="INFO",
            logger_name=LOGGER.name,
            event="worker_symbol_cycle_key_registered",
            payload={
                "symbol": symbol,
                "cycle_key": cycle_key,
                "heartbeat_cycle_key": heartbeat_cycle_key,
                "service": service_key,
            },
        )

        start_run(run_id=run_id)
        try:
            data = self.loader.load(
                symbol=symbol,
                timeframe=self._execution_timeframe,
                force_refresh=False,
            )
            latest_price = float(data["close"].iloc[-1])
            latest_timestamp = pd.Timestamp(data.index[-1])
            current_position = executor.positions.get(symbol)
            persisted_configs = self.repository.load_strategy_configs()

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
            market_regime = self._determine_market_regime(
                data=data,
                persisted_configs=persisted_configs,
            )
            LOGGER.info(
                "market_regime_evaluated cycle_key=%s symbol=%s regime=%s short_ma=%s long_ma=%s spread_pct=%s",
                cycle_key,
                symbol,
                market_regime.regime,
                (
                    f"{market_regime.short_moving_average:.6f}"
                    if market_regime.short_moving_average is not None
                    else "na"
                ),
                (
                    f"{market_regime.long_moving_average:.6f}"
                    if market_regime.long_moving_average is not None
                    else "na"
                ),
                (
                    f"{market_regime.spread_pct:.6f}"
                    if market_regime.spread_pct is not None
                    else "na"
                ),
            )
            self.repository.append_log_event(
                level="INFO",
                logger_name=LOGGER.name,
                event="market_regime_evaluated",
                run_id=run_id,
                payload={
                    "cycle_key": cycle_key,
                    "symbol": symbol,
                    "market_regime": market_regime.regime,
                    "short_moving_average": market_regime.short_moving_average,
                    "long_moving_average": market_regime.long_moving_average,
                    "spread_pct": market_regime.spread_pct,
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
                persisted_configs=persisted_configs,
            )
            candidates = self._apply_strategy_gates_for_new_entries(
                candidates=candidates,
                symbol=symbol,
                latest_price=latest_price,
                latest_timestamp=latest_timestamp,
                current_position=current_position,
                market_regime=market_regime,
                persisted_configs=persisted_configs,
                cycle_key=cycle_key,
                run_id=run_id,
            )
            selection_state = self._build_global_selection_state(
                executor=executor,
                latest_price=latest_price,
                symbol=symbol,
                warmup_active=warmup_active,
            )
            selector_for_cycle = self._selector_for_cycle(
                effective_min_recent_trades=effective_min_recent_trades
            )
            decision = selector_for_cycle.select(
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

            order_plan = self._plan_order(
                symbol=symbol,
                decision=decision,
                selected_signal=selected_signal,
                latest_price=latest_price,
                latest_timestamp=latest_timestamp,
                current_position=current_position,
                executor=executor,
                market_regime=market_regime,
                persisted_configs=persisted_configs,
                cycle_key=cycle_key,
                run_id=run_id,
            )
            order = order_plan.order

            if order is None:
                no_trade_reason = order_plan.no_trade_reason or self._determine_no_trade_reason(
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
                        "rejection_reasons": list(order_plan.rejection_reasons),
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
                        "rejection_reasons": list(order_plan.rejection_reasons),
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
                    rejection_reasons=order_plan.rejection_reasons,
                )

            if self.settings.worker_dry_run:
                LOGGER.info(
                    "worker_order_eligible_but_skipped_dry_run cycle_key=%s symbol=%s side=%s qty=%.6f price=%.6f selected_strategy=%s",
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
                        "skip_classification": "eligible_but_skipped_dry_run",
                        "timeframe": self._execution_timeframe,
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
        persisted_configs: dict[str, dict[str, Any]] | None = None,
    ) -> list[StrategyCandidate]:
        """Build normalized candidate inputs for all registered strategies."""
        if persisted_configs is None:
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
        warmup_active: bool,
    ) -> GlobalSelectionState:
        """Compute global gating state for deterministic eligibility checks."""
        current_equity = executor.current_equity()
        required_quantity = 1.0 if self.settings.enable_position_sizing else self.settings.worker_order_quantity
        required_notional = float(required_quantity * latest_price)
        max_position_notional = float(self.settings.max_position_size * current_equity)
        available_notional = float(min(self.settings.max_notional_per_trade, max_position_notional))

        active_positions = sum(1 for item in executor.positions.values() if item.quantity > EPSILON)
        has_symbol_position = (
            executor.positions.get(symbol) is not None
            and float(executor.positions[symbol].quantity) > EPSILON
        )
        max_positions_breached = (
            active_positions >= self._effective_max_open_positions() and not has_symbol_position
        )

        return GlobalSelectionState(
            kill_switch_enabled=self.repository.get_global_kill_switch(),
            paper_trading_enabled=(
                self.settings.paper_trading_enabled or self.settings.worker_dry_run
            ),
            worker_enable_trading=self.settings.worker_enable_trading,
            risk_budget_available=(
                required_notional <= available_notional + EPSILON
                and required_notional <= executor.cash + EPSILON
            ),
            max_positions_breached=max_positions_breached,
            warmup_mode=warmup_active,
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
            if not candidate.eligible:
                rejection_classification = self._classify_rejection_reasons(candidate.reasons)
                if rejection_classification == "strategy_logic":
                    LOGGER.info(
                        "strategy_not_eligible cycle_key=%s symbol=%s strategy=%s reason_class=strategy_logic reasons=%s",
                        cycle_key,
                        symbol,
                        candidate.strategy,
                        ",".join(candidate.reasons) if candidate.reasons else "none",
                    )
                self.repository.append_log_event(
                    level="INFO",
                    logger_name=LOGGER.name,
                    event="strategy_not_eligible",
                    run_id=run_id,
                    payload={
                        "cycle_key": cycle_key,
                        "symbol": symbol,
                        "strategy": candidate.strategy,
                        "reason_classification": rejection_classification,
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

    def _determine_market_regime(
        self,
        data: pd.DataFrame,
        persisted_configs: dict[str, dict[str, Any]],
    ) -> MarketRegimeEvaluation:
        """Evaluate the MA-crossover regime used by the additive gating layer."""
        regime_params = self._resolve_strategy_parameters(
            "moving_average_crossover",
            persisted_configs.get("moving_average_crossover", {}),
        )
        short_window = int(regime_params.get("short_window", 20))
        long_window = int(regime_params.get("long_window", 50))
        return get_market_regime(
            data,
            short_window=short_window,
            long_window=long_window,
            threshold_pct=self.settings.market_regime_threshold_pct,
        )

    def _apply_strategy_gates_for_new_entries(
        self,
        candidates: list[StrategyCandidate],
        symbol: str,
        latest_price: float,
        latest_timestamp: pd.Timestamp,
        current_position: Position | None,
        market_regime: MarketRegimeEvaluation,
        persisted_configs: dict[str, dict[str, Any]],
        cycle_key: str,
        run_id: str,
    ) -> list[StrategyCandidate]:
        """Add regime gate reasons to entry candidates without disturbing exits."""
        current_qty = 0.0 if current_position is None else float(current_position.quantity)
        if not self.settings.enable_strategy_gating or current_qty > EPSILON:
            return candidates

        gate_config = self._strategy_gate_config()
        gated_candidates: list[StrategyCandidate] = []
        for candidate in candidates:
            if candidate.signal <= EPSILON:
                gated_candidates.append(candidate)
                continue

            intent = self._build_trade_intent(
                symbol=symbol,
                strategy_name=candidate.strategy,
                latest_price=latest_price,
                latest_timestamp=latest_timestamp,
                signal=candidate.signal,
                market_regime=market_regime,
                persisted_configs=persisted_configs,
            )
            if intent is None:
                gated_candidates.append(candidate)
                continue

            _, gate_decision = gate_trade_intent(intent, config=gate_config)
            if gate_decision.approved:
                gated_candidates.append(candidate)
                continue

            self._log_trade_intent_rejection(
                run_id=run_id,
                cycle_key=cycle_key,
                symbol=symbol,
                strategy_name=candidate.strategy,
                stage="strategy_gate",
                reasons=gate_decision.reasons,
                market_regime=market_regime.regime,
            )
            gated_candidates.append(
                replace(
                    candidate,
                    external_reasons=tuple(
                        dict.fromkeys((*candidate.external_reasons, *gate_decision.reasons))
                    ),
                )
            )
        return gated_candidates

    def _plan_order(
        self,
        symbol: str,
        decision: SelectionDecision,
        selected_signal: float,
        latest_price: float,
        latest_timestamp: pd.Timestamp,
        current_position: Position | None,
        executor: PaperTradingExecutor,
        market_regime: MarketRegimeEvaluation,
        persisted_configs: dict[str, dict[str, Any]],
        cycle_key: str,
        run_id: str,
    ) -> OrderPlanningResult:
        """Prepare an order using optional gating, sizing, and risk-policy layers."""
        current_qty = 0.0 if current_position is None else float(current_position.quantity)
        if current_qty > EPSILON:
            order = self._build_order(
                symbol=symbol,
                selected_strategy=decision.selected_strategy,
                selected_signal=selected_signal,
                latest_price=latest_price,
                latest_timestamp=latest_timestamp,
                current_position=current_position,
                sizing_multiplier=decision.sizing_multiplier,
            )
            return OrderPlanningResult(order=order)

        if decision.selected_strategy is None or selected_signal <= EPSILON:
            return OrderPlanningResult(order=None)

        if not (
            self.settings.enable_strategy_gating
            or self.settings.enable_position_sizing
            or self.settings.enable_risk_caps
        ):
            return OrderPlanningResult(
                order=self._build_order(
                    symbol=symbol,
                    selected_strategy=decision.selected_strategy,
                    selected_signal=selected_signal,
                    latest_price=latest_price,
                    latest_timestamp=latest_timestamp,
                    current_position=current_position,
                    sizing_multiplier=decision.sizing_multiplier,
                )
            )

        intent = self._build_trade_intent(
            symbol=symbol,
            strategy_name=decision.selected_strategy,
            latest_price=latest_price,
            latest_timestamp=latest_timestamp,
            signal=selected_signal,
            market_regime=market_regime,
            persisted_configs=persisted_configs,
        )
        if intent is None:
            return OrderPlanningResult(order=None, no_trade_reason="unsupported_trade_intent")

        gated_intent = None
        if self.settings.enable_strategy_gating:
            gated_intent, gate_decision = gate_trade_intent(
                intent,
                config=self._strategy_gate_config(),
            )
            if not gate_decision.approved:
                self._log_trade_intent_rejection(
                    run_id=run_id,
                    cycle_key=cycle_key,
                    symbol=symbol,
                    strategy_name=decision.selected_strategy,
                    stage="strategy_gate",
                    reasons=gate_decision.reasons,
                    market_regime=market_regime.regime,
                )
                return OrderPlanningResult(
                    order=None,
                    no_trade_reason=f"trade_intent_rejected:{gate_decision.reasons[0]}",
                    rejection_reasons=tuple(gate_decision.reasons),
                )
        else:
            gated_intent = self._wrap_trade_intent_without_gate(intent)

        risk_state = self._build_trading_risk_state(
            executor=executor,
            symbol=symbol,
            latest_price=latest_price,
        )

        if self.settings.enable_position_sizing:
            sized_intent, sizing_decision = calculate_position_size(
                gated_intent,
                state=risk_state,
                config=self._position_sizing_config(),
            )
            if not sizing_decision.approved:
                self._log_trade_intent_rejection(
                    run_id=run_id,
                    cycle_key=cycle_key,
                    symbol=symbol,
                    strategy_name=decision.selected_strategy,
                    stage="position_sizing",
                    reasons=sizing_decision.reasons,
                    market_regime=market_regime.regime,
                )
                return OrderPlanningResult(
                    order=None,
                    no_trade_reason=f"trade_intent_rejected:{sizing_decision.reasons[0]}",
                    rejection_reasons=tuple(sizing_decision.reasons),
                )
            self._log_sized_trade_intent(
                run_id=run_id,
                cycle_key=cycle_key,
                sized_intent=sized_intent,
            )
            quantity = float(sized_intent.quantity)
            proposed_notional = float(sized_intent.projected_notional)
            final_stop_loss_pct = sized_intent.stop_loss_pct
            trailing_stop_pct = sized_intent.trailing_stop_pct
        else:
            quantity = float(self.settings.worker_order_quantity * max(decision.sizing_multiplier, 0.0))
            proposed_notional = float(quantity * latest_price)
            final_stop_loss_pct = gated_intent.stop_loss_pct
            trailing_stop_pct = gated_intent.trailing_stop_pct
            if quantity <= EPSILON:
                return OrderPlanningResult(order=None, no_trade_reason="sizing_multiplier_zero")

        if self.settings.enable_risk_caps:
            risk_decision = evaluate_risk_policy(
                gated_intent,
                state=risk_state,
                config=self._risk_policy_config(),
                proposed_notional=proposed_notional,
            )
            if not risk_decision.approved:
                self._log_trade_intent_rejection(
                    run_id=run_id,
                    cycle_key=cycle_key,
                    symbol=symbol,
                    strategy_name=decision.selected_strategy,
                    stage="risk_policy",
                    reasons=risk_decision.reasons,
                    market_regime=market_regime.regime,
                )
                return OrderPlanningResult(
                    order=None,
                    no_trade_reason=f"trade_intent_rejected:{risk_decision.reasons[0]}",
                    rejection_reasons=tuple(risk_decision.reasons),
                )

        return OrderPlanningResult(
            order=Order(
                symbol=symbol,
                side="BUY",
                quantity=quantity,
                price=latest_price,
                timestamp=latest_timestamp,
                stop_loss_pct=final_stop_loss_pct,
                trailing_stop_pct=trailing_stop_pct,
            )
        )

    def _build_trade_intent(
        self,
        symbol: str,
        strategy_name: str,
        latest_price: float,
        latest_timestamp: pd.Timestamp,
        signal: float,
        market_regime: MarketRegimeEvaluation,
        persisted_configs: dict[str, dict[str, Any]],
    ) -> TradeIntent | None:
        """Build a typed trade intent for a selected long-entry strategy."""
        strategy_id = normalize_strategy_id(strategy_name)
        if strategy_id is None:
            return None

        strategy_params = self._resolve_strategy_parameters(
            strategy_name,
            persisted_configs.get(strategy_name, {}),
        )
        stop_price = _coerce_float(strategy_params.get("stop_price"))
        stop_loss_pct = _coerce_float(strategy_params.get("stop_loss_pct"))
        trailing_stop_pct = _coerce_float(strategy_params.get("trailing_stop_pct"))
        if stop_loss_pct is None:
            stop_loss_pct = self.settings.default_stop_loss_pct_for_sizing
        if stop_price is None and stop_loss_pct is not None:
            stop_price = latest_price * (1.0 - stop_loss_pct)

        return TradeIntent(
            symbol=symbol,
            strategy_id=strategy_id,
            side="BUY",
            entry_price=float(latest_price),
            timestamp=latest_timestamp,
            signal=float(signal),
            regime=market_regime.regime,
            stop_price=stop_price,
            stop_loss_pct=stop_loss_pct,
            trailing_stop_pct=trailing_stop_pct,
        )

    def _wrap_trade_intent_without_gate(self, intent: TradeIntent) -> GatedTradeIntent:
        """Wrap a raw trade intent with a neutral size multiplier."""
        return GatedTradeIntent(
            symbol=intent.symbol,
            strategy_id=intent.strategy_id,
            side=intent.side,
            entry_price=float(intent.entry_price),
            timestamp=intent.timestamp,
            signal=float(intent.signal),
            regime=intent.regime,
            stop_price=intent.stop_price,
            stop_loss_pct=intent.stop_loss_pct,
            trailing_stop_pct=intent.trailing_stop_pct,
            regime_size_multiplier=1.0,
        )

    def _build_trading_risk_state(
        self,
        executor: PaperTradingExecutor,
        symbol: str,
        latest_price: float,
    ) -> TradingRiskState:
        """Build lightweight account state for additive trade controls."""
        gross_exposure = 0.0
        active_positions = 0
        for position_symbol, position in executor.positions.items():
            quantity = float(position.quantity)
            if quantity <= EPSILON:
                continue
            active_positions += 1
            price = latest_price if position_symbol == symbol else float(position.avg_price)
            gross_exposure += abs(quantity * price)

        return TradingRiskState(
            account_equity=float(executor.current_equity()),
            day_start_equity=float(executor.day_start_equity),
            gross_exposure=float(gross_exposure),
            active_positions=active_positions,
        )

    def _strategy_gate_config(self) -> StrategyGateConfig:
        """Build config for the additive strategy gate."""
        return StrategyGateConfig(
            allow_rsi_in_bullish=self.settings.allow_rsi_in_bullish_regime,
            allow_bearish_mean_reversion=self.settings.allow_bearish_mean_reversion,
            bullish_regime_size_multiplier=self.settings.bullish_regime_size_multiplier,
            sideways_regime_size_multiplier=self.settings.sideways_regime_size_multiplier,
            bearish_regime_size_multiplier=self.settings.bearish_regime_size_multiplier,
        )

    def _position_sizing_config(self) -> PositionSizingConfig:
        """Build config for fixed-risk position sizing."""
        return PositionSizingConfig(
            risk_per_trade_pct=self.settings.risk_per_trade_pct,
            max_portfolio_exposure_pct=self.settings.max_portfolio_exposure_pct,
            max_concurrent_positions=self.settings.max_concurrent_positions,
        )

    def _risk_policy_config(self) -> RiskPolicyConfig:
        """Build config for additive risk caps."""
        return RiskPolicyConfig(
            daily_drawdown_limit_pct=self.settings.daily_drawdown_limit_pct,
            max_concurrent_positions=self.settings.max_concurrent_positions,
            max_portfolio_exposure_pct=self.settings.max_portfolio_exposure_pct,
        )

    def _effective_max_open_positions(self) -> int:
        """Return the open-position cap used by the existing executor layer."""
        if self.settings.enable_position_sizing or self.settings.enable_risk_caps:
            return self.settings.max_concurrent_positions
        return self.settings.max_open_positions

    def _effective_max_gross_exposure(self) -> float:
        """Return gross exposure passed to the existing risk manager."""
        if self.settings.enable_position_sizing or self.settings.enable_risk_caps:
            return self.settings.max_portfolio_exposure_pct
        return 1.0

    def _log_trade_intent_rejection(
        self,
        run_id: str,
        cycle_key: str,
        symbol: str,
        strategy_name: str,
        stage: str,
        reasons: tuple[str, ...],
        market_regime: str,
    ) -> None:
        """Emit structured logs for additive trade-intent rejections."""
        LOGGER.info(
            "trade_intent_rejected cycle_key=%s symbol=%s strategy=%s stage=%s market_regime=%s reasons=%s",
            cycle_key,
            symbol,
            strategy_name,
            stage,
            market_regime,
            ",".join(reasons),
        )
        self.repository.append_log_event(
            level="INFO",
            logger_name=LOGGER.name,
            event="trade_intent_rejected",
            run_id=run_id,
            payload={
                "cycle_key": cycle_key,
                "symbol": symbol,
                "strategy": strategy_name,
                "stage": stage,
                "market_regime": market_regime,
                "reasons": list(reasons),
            },
        )

    def _log_sized_trade_intent(
        self,
        run_id: str,
        cycle_key: str,
        sized_intent: Any,
    ) -> None:
        """Emit one structured log for a successfully sized entry."""
        LOGGER.info(
            "trade_intent_sized cycle_key=%s symbol=%s strategy=%s regime=%s qty=%d dollars_at_risk=%.2f risk_per_share=%.6f notional=%.2f",
            cycle_key,
            sized_intent.symbol,
            sized_intent.strategy_id,
            sized_intent.regime,
            sized_intent.quantity,
            sized_intent.dollars_at_risk,
            sized_intent.risk_per_share,
            sized_intent.projected_notional,
        )
        self.repository.append_log_event(
            level="INFO",
            logger_name=LOGGER.name,
            event="trade_intent_sized",
            run_id=run_id,
            payload={
                "cycle_key": cycle_key,
                "symbol": sized_intent.symbol,
                "strategy": sized_intent.strategy_id,
                "market_regime": sized_intent.regime,
                "quantity": int(sized_intent.quantity),
                "dollars_at_risk": float(sized_intent.dollars_at_risk),
                "risk_per_share": float(sized_intent.risk_per_share),
                "projected_notional": float(sized_intent.projected_notional),
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

    def _selector_for_cycle(self, effective_min_recent_trades: int) -> StrategySelector:
        """Return selector configured for the current cycle warm-up state."""
        base = self.selector.config
        if effective_min_recent_trades == base.min_recent_trades:
            return self.selector
        return StrategySelector(
            config=SelectionConfig(
                max_recent_drawdown=base.max_recent_drawdown,
                min_recent_expectancy=base.min_recent_expectancy,
                min_recent_trades=effective_min_recent_trades,
                min_score_threshold=base.min_score_threshold,
                mediocre_score_threshold=base.mediocre_score_threshold,
                mediocre_size_multiplier=base.mediocre_size_multiplier,
                top_n=base.top_n,
            )
        )

    @staticmethod
    def _classify_rejection_reasons(reasons: tuple[str, ...]) -> str:
        """Classify rejection reasons for operational logging."""
        if not reasons:
            return "none"
        has_global_gate = any(
            reason in GLOBAL_GATE_REASONS
            or reason.startswith("symbol_locked_by_active_strategy:")
            for reason in reasons
        )
        has_strategy_logic = any(reason in STRATEGY_LOGIC_REASONS for reason in reasons)
        if has_strategy_logic and not has_global_gate:
            return "strategy_logic"
        if has_global_gate and not has_strategy_logic:
            return "global_gate"
        if has_strategy_logic and has_global_gate:
            return "mixed"
        return "other"

    def _heartbeat_cycle_key(self, timestamp: pd.Timestamp) -> str:
        """Derive a cross-universe cycle key for worker heartbeat updates."""
        poll_seconds = max(1, int(self.settings.worker_poll_seconds))
        ts = pd.Timestamp(timestamp)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        bucketed = ts.floor(f"{poll_seconds}s")
        return f"{self._execution_timeframe}:{bucketed.strftime('%Y-%m-%dT%H:%M:%SZ')}"

    def _cycle_key(self, symbol: str, heartbeat_cycle_key: str) -> str:
        """Derive per-symbol cycle key for idempotent symbol execution."""
        return f"{symbol}:{heartbeat_cycle_key}"
