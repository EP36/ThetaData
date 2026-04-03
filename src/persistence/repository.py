"""Persistence repository for API + worker runtime state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.execution.models import Fill, Order, Position
from src.persistence.models import (
    BacktestTradeModel,
    FillModel,
    GlobalStateModel,
    LogEventModel,
    OrderModel,
    PortfolioStateModel,
    PositionModel,
    RunHistoryModel,
    SymbolStrategyLockModel,
    StrategyConfigModel,
    WorkerHeartbeatModel,
)
from src.persistence.store import DatabaseStore


def utc_now() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """Serializable portfolio state snapshot for executor restore."""

    cash: float
    day_start_equity: float
    peak_equity: float
    positions: dict[str, Position]


@dataclass(slots=True)
class PersistenceRepository:
    """Repository encapsulating all DB reads/writes."""

    store: DatabaseStore

    def initialize(self, starting_cash: float = 100_000.0) -> None:
        """Create schema and ensure singleton defaults exist."""
        self.store.create_schema()
        with self.store.session() as session:
            global_state = session.get(GlobalStateModel, 1)
            if global_state is None:
                global_state = GlobalStateModel(id=1, kill_switch_enabled=False, reason="")
                session.add(global_state)

            portfolio_state = session.get(PortfolioStateModel, 1)
            if portfolio_state is None:
                portfolio_state = PortfolioStateModel(
                    id=1,
                    cash=starting_cash,
                    day_start_equity=starting_cash,
                    peak_equity=starting_cash,
                )
                session.add(portfolio_state)

    def healthcheck(self) -> bool:
        """Return True if DB is reachable."""
        return self.store.ping()

    def get_global_kill_switch(self) -> bool:
        """Fetch global kill-switch state."""
        with self.store.session() as session:
            state = session.get(GlobalStateModel, 1)
            return bool(state.kill_switch_enabled) if state is not None else False

    def set_global_kill_switch(self, enabled: bool, reason: str = "") -> bool:
        """Set and persist global kill-switch state."""
        with self.store.session() as session:
            state = session.get(GlobalStateModel, 1)
            if state is None:
                state = GlobalStateModel(id=1)
                session.add(state)
            state.kill_switch_enabled = bool(enabled)
            state.reason = reason.strip()
            state.updated_at = utc_now()
            return state.kill_switch_enabled

    def upsert_strategy_config(
        self,
        name: str,
        status: str,
        parameters: dict[str, Any],
    ) -> None:
        """Insert/update strategy config row."""
        with self.store.session() as session:
            row = session.get(StrategyConfigModel, name)
            if row is None:
                row = StrategyConfigModel(
                    name=name,
                    status=status,
                    parameters=dict(parameters),
                )
                session.add(row)
            else:
                row.status = status
                row.parameters = dict(parameters)
                row.updated_at = utc_now()

    def load_strategy_configs(self) -> dict[str, dict[str, Any]]:
        """Return strategy configs keyed by strategy name."""
        with self.store.session() as session:
            rows = session.scalars(select(StrategyConfigModel)).all()
            return {
                row.name: {
                    "status": row.status,
                    "parameters": dict(row.parameters or {}),
                    "updated_at": row.updated_at,
                }
                for row in rows
            }

    def list_symbol_strategy_locks(self) -> dict[str, dict[str, Any]]:
        """Return active strategy locks keyed by symbol."""
        with self.store.session() as session:
            rows = session.scalars(select(SymbolStrategyLockModel)).all()
            return {
                row.symbol.upper(): {
                    "strategy": row.strategy,
                    "run_id": row.run_id,
                    "reason": row.reason,
                    "updated_at": row.updated_at,
                }
                for row in rows
            }

    def upsert_symbol_strategy_lock(
        self,
        symbol: str,
        strategy: str,
        run_id: str | None = None,
        reason: str = "",
    ) -> None:
        """Persist or update the active strategy lock for a symbol."""
        symbol_key = symbol.strip().upper()
        if not symbol_key:
            raise ValueError("symbol cannot be empty")
        strategy_key = strategy.strip()
        if not strategy_key:
            raise ValueError("strategy cannot be empty")
        with self.store.session() as session:
            row = session.get(SymbolStrategyLockModel, symbol_key)
            if row is None:
                row = SymbolStrategyLockModel(symbol=symbol_key, strategy=strategy_key)
                session.add(row)
            row.strategy = strategy_key
            row.run_id = run_id
            row.reason = reason.strip()
            row.updated_at = utc_now()

    def release_symbol_strategy_lock(self, symbol: str) -> None:
        """Remove active strategy lock for one symbol when no longer needed."""
        symbol_key = symbol.strip().upper()
        if not symbol_key:
            return
        with self.store.session() as session:
            row = session.get(SymbolStrategyLockModel, symbol_key)
            if row is not None:
                session.delete(row)

    def record_worker_heartbeat(
        self,
        worker_name: str,
        status: str,
        last_cycle_key: str | None = None,
        message: str = "",
    ) -> None:
        """Write worker heartbeat data."""
        with self.store.session() as session:
            row = session.get(WorkerHeartbeatModel, worker_name)
            if row is None:
                row = WorkerHeartbeatModel(worker_name=worker_name)
                session.add(row)
            row.status = status
            row.last_cycle_key = last_cycle_key
            row.message = message
            row.updated_at = utc_now()

    def get_worker_heartbeat(self, worker_name: str) -> dict[str, Any] | None:
        """Return worker heartbeat info, if available."""
        with self.store.session() as session:
            row = session.get(WorkerHeartbeatModel, worker_name)
            if row is None:
                return None
            return {
                "worker_name": row.worker_name,
                "status": row.status,
                "last_cycle_key": row.last_cycle_key,
                "message": row.message,
                "updated_at": row.updated_at,
            }

    def start_run(
        self,
        run_id: str,
        service: str,
        cycle_key: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        strategy: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """Create run record; return False when duplicate cycle is detected."""
        with self.store.session() as session:
            row = RunHistoryModel(
                run_id=run_id,
                service=service,
                cycle_key=cycle_key,
                symbol=symbol,
                timeframe=timeframe,
                strategy=strategy,
                status="running",
                details=dict(details or {}),
                started_at=utc_now(),
            )
            session.add(row)
            try:
                session.flush()
                return True
            except IntegrityError:
                session.rollback()
                return False

    def get_run_by_service_cycle_key(
        self,
        service: str,
        cycle_key: str,
    ) -> dict[str, Any] | None:
        """Return one run row by service/cycle key, when present."""
        with self.store.session() as session:
            row = session.scalar(
                select(RunHistoryModel)
                .where(
                    RunHistoryModel.service == service,
                    RunHistoryModel.cycle_key == cycle_key,
                )
                .limit(1)
            )
            if row is None:
                return None
            return {
                "run_id": row.run_id,
                "service": row.service,
                "cycle_key": row.cycle_key,
                "status": row.status,
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "strategy": row.strategy,
                "details": dict(row.details or {}),
                "error_message": row.error_message,
                "started_at": row.started_at,
                "completed_at": row.completed_at,
            }

    def finish_run(
        self,
        run_id: str,
        status: str,
        error_message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Mark run as completed/failed with optional detail payload."""
        with self.store.session() as session:
            row = session.scalar(select(RunHistoryModel).where(RunHistoryModel.run_id == run_id))
            if row is None:
                return
            row.status = status
            row.error_message = error_message
            if details is not None:
                merged = dict(row.details or {})
                merged.update(details)
                row.details = merged
            row.completed_at = utc_now()

    def compute_order_dedupe_key(
        self,
        cycle_key: str,
        order: Order,
    ) -> str:
        """Build stable dedupe key for idempotent order insertion."""
        payload = (
            f"{cycle_key}|{order.symbol.upper()}|{order.side.upper()}|"
            f"{order.quantity:.8f}|{order.price:.8f}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def order_exists_by_dedupe_key(self, dedupe_key: str) -> bool:
        """Return True if an order with dedupe key already exists."""
        with self.store.session() as session:
            row = session.scalar(select(OrderModel).where(OrderModel.dedupe_key == dedupe_key))
            return row is not None

    def record_order(
        self,
        order: Order,
        source: str,
        run_id: str | None = None,
        dedupe_key: str | None = None,
    ) -> bool:
        """Persist one order row; False when rejected by dedupe uniqueness."""
        with self.store.session() as session:
            row = OrderModel(
                order_id=order.order_id,
                dedupe_key=dedupe_key,
                run_id=run_id,
                source=source,
                symbol=order.symbol,
                side=order.side.upper(),
                quantity=float(order.quantity),
                price=float(order.price),
                notional=float(order.quantity * order.price),
                status=order.status,
                rejection_reasons=list(order.rejection_reasons),
                created_at=order.timestamp.to_pydatetime()
                if hasattr(order.timestamp, "to_pydatetime")
                else utc_now(),
            )
            session.add(row)
            try:
                session.flush()
                return True
            except IntegrityError:
                session.rollback()
                return False

    def update_order_status(
        self,
        order_id: str,
        status: str,
        rejection_reasons: tuple[str, ...] = (),
    ) -> None:
        """Update mutable order fields after execution result."""
        with self.store.session() as session:
            row = session.scalar(select(OrderModel).where(OrderModel.order_id == order_id))
            if row is None:
                return
            row.status = status
            row.rejection_reasons = list(rejection_reasons)

    def record_fill(self, fill: Fill, run_id: str | None = None) -> None:
        """Persist one fill row."""
        with self.store.session() as session:
            fill_id = hashlib.sha256(
                f"{fill.order_id}|{fill.timestamp.isoformat()}|{fill.quantity:.8f}|{fill.price:.8f}".encode(
                    "utf-8"
                )
            ).hexdigest()
            row = FillModel(
                fill_id=fill_id,
                order_id=fill.order_id,
                run_id=run_id,
                symbol=fill.symbol,
                side=fill.side.upper(),
                quantity=float(fill.quantity),
                price=float(fill.price),
                notional=float(fill.notional),
                timestamp=fill.timestamp.to_pydatetime()
                if hasattr(fill.timestamp, "to_pydatetime")
                else utc_now(),
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                # Idempotent replays should not duplicate fills.
                session.rollback()
                return

    def record_backtest_trade(
        self,
        run_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        fee: float,
        reason: str,
        strategy: str,
        timeframe: str,
        timestamp: datetime,
    ) -> None:
        """Persist one backtest trade row in the backtest-only table."""
        trade_key = hashlib.sha256(
            (
                f"{run_id}|{symbol.upper()}|{side.upper()}|{quantity:.8f}|"
                f"{price:.8f}|{timestamp.isoformat()}"
            ).encode("utf-8")
        ).hexdigest()
        with self.store.session() as session:
            row = BacktestTradeModel(
                backtest_trade_id=trade_key,
                run_id=run_id,
                symbol=symbol.upper(),
                side=side.upper(),
                quantity=float(quantity),
                price=float(price),
                fee=float(fee),
                reason=reason.strip(),
                strategy=strategy,
                timeframe=timeframe,
                timestamp=timestamp,
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                return

    def save_portfolio_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        """Persist cash/equity anchors and positions."""
        with self.store.session() as session:
            portfolio_row = session.get(PortfolioStateModel, 1)
            if portfolio_row is None:
                portfolio_row = PortfolioStateModel(id=1)
                session.add(portfolio_row)
            portfolio_row.cash = snapshot.cash
            portfolio_row.day_start_equity = snapshot.day_start_equity
            portfolio_row.peak_equity = snapshot.peak_equity
            portfolio_row.updated_at = utc_now()

            existing_symbols = {
                row.symbol: row for row in session.scalars(select(PositionModel)).all()
            }
            incoming_symbols = set(snapshot.positions.keys())

            for symbol, position in snapshot.positions.items():
                row = existing_symbols.get(symbol)
                if row is None:
                    row = PositionModel(symbol=symbol)
                    session.add(row)
                row.quantity = float(position.quantity)
                row.avg_price = float(position.avg_price)
                row.realized_pnl = float(position.realized_pnl)
                row.unrealized_pnl = float(position.unrealized_pnl)
                row.updated_at = utc_now()

            for symbol, row in existing_symbols.items():
                if symbol not in incoming_symbols:
                    session.delete(row)

    def load_portfolio_snapshot(self, default_cash: float) -> PortfolioSnapshot:
        """Load latest portfolio snapshot for executor restore."""
        with self.store.session() as session:
            portfolio_row = session.get(PortfolioStateModel, 1)
            if portfolio_row is None:
                return PortfolioSnapshot(
                    cash=default_cash,
                    day_start_equity=default_cash,
                    peak_equity=default_cash,
                    positions={},
                )

            position_rows = session.scalars(select(PositionModel)).all()
            positions = {
                row.symbol: Position(
                    symbol=row.symbol,
                    quantity=float(row.quantity),
                    avg_price=float(row.avg_price),
                    realized_pnl=float(row.realized_pnl),
                    unrealized_pnl=float(row.unrealized_pnl),
                )
                for row in position_rows
            }
            return PortfolioSnapshot(
                cash=float(portfolio_row.cash),
                day_start_equity=float(portfolio_row.day_start_equity),
                peak_equity=float(portfolio_row.peak_equity),
                positions=positions,
            )

    def recent_fills(
        self,
        limit: int = 200,
        run_service_prefix: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent fills with lightweight run context for API consumers."""
        with self.store.session() as session:
            statement = (
                select(FillModel, RunHistoryModel)
                .outerjoin(RunHistoryModel, FillModel.run_id == RunHistoryModel.run_id)
                .order_by(FillModel.timestamp.desc())
            )
            if run_service_prefix:
                statement = statement.where(
                    RunHistoryModel.service.like(f"{run_service_prefix}%")
                )
            rows = session.execute(statement.limit(limit)).all()
            records: list[dict[str, Any]] = []
            for fill_row, run_row in rows:
                details = dict(run_row.details or {}) if run_row is not None else {}
                selection = details.get("selection")
                selected_strategy = None
                if isinstance(selection, dict):
                    selected_strategy = selection.get("selected_strategy")
                strategy = str(
                    selected_strategy
                    or (run_row.strategy if run_row is not None else None)
                    or "paper_worker"
                )
                service = str(run_row.service) if run_row is not None else ""
                records.append(
                    {
                        "order_id": fill_row.order_id,
                        "run_id": fill_row.run_id,
                        "timestamp": fill_row.timestamp,
                        "symbol": fill_row.symbol,
                        "side": fill_row.side.upper(),
                        "quantity": float(fill_row.quantity),
                        "price": float(fill_row.price),
                        "strategy": strategy,
                        "service": service,
                    }
                )
            return records

    def recent_backtest_trades(self, limit: int = 2000) -> list[dict[str, Any]]:
        """Return recent persisted backtest trades."""
        with self.store.session() as session:
            rows = session.scalars(
                select(BacktestTradeModel)
                .order_by(BacktestTradeModel.timestamp.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "run_id": row.run_id,
                    "timestamp": row.timestamp,
                    "symbol": row.symbol,
                    "side": row.side.upper(),
                    "quantity": float(row.quantity),
                    "price": float(row.price),
                    "fee": float(row.fee),
                    "reason": row.reason,
                    "strategy": row.strategy,
                    "timeframe": row.timeframe,
                }
                for row in rows
            ]

    def append_log_event(
        self,
        level: str,
        logger_name: str,
        event: str,
        run_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Persist one structured log event."""
        with self.store.session() as session:
            session.add(
                LogEventModel(
                    run_id=run_id,
                    level=level.upper(),
                    logger=logger_name,
                    event=event,
                    payload=dict(payload or {}),
                    timestamp=utc_now(),
                )
            )

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return latest run-history rows for API status views."""
        with self.store.session() as session:
            rows = session.scalars(
                select(RunHistoryModel).order_by(RunHistoryModel.started_at.desc()).limit(limit)
            ).all()
            return [
                {
                    "run_id": row.run_id,
                    "service": row.service,
                    "cycle_key": row.cycle_key,
                    "status": row.status,
                    "symbol": row.symbol,
                    "timeframe": row.timeframe,
                    "strategy": row.strategy,
                    "details": dict(row.details or {}),
                    "error_message": row.error_message,
                    "started_at": row.started_at,
                    "completed_at": row.completed_at,
                }
                for row in rows
            ]

    def recent_log_events(
        self,
        limit: int = 200,
        event: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return latest structured log events, optionally filtered by event name."""
        with self.store.session() as session:
            query = select(LogEventModel)
            if event is not None:
                query = query.where(LogEventModel.event == event)
            rows = session.scalars(
                query.order_by(LogEventModel.timestamp.desc()).limit(limit)
            ).all()
            return [
                {
                    "id": row.id,
                    "run_id": row.run_id,
                    "level": row.level,
                    "logger": row.logger,
                    "event": row.event,
                    "payload": dict(row.payload or {}),
                    "timestamp": row.timestamp,
                }
                for row in rows
            ]
