"""Paper trading executor with risk validation and PnL tracking."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
from pathlib import Path

import pandas as pd

from src.execution.broker import PaperBroker, SimulatedPaperBroker
from src.execution.models import (
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_REJECTED,
    ORDER_STATUS_SUBMITTED,
    Fill,
    Order,
    Position,
)
from src.risk.manager import RiskManager
from src.risk.models import OrderRiskRequest, PortfolioRiskState

LOGGER = logging.getLogger("theta.execution.executor")


@dataclass(slots=True)
class PaperTradingExecutor:
    """Paper-only executor with explicit safety controls."""

    starting_cash: float
    risk_manager: RiskManager
    broker: PaperBroker = field(default_factory=SimulatedPaperBroker)
    paper_trading_enabled: bool = False
    max_notional_per_trade: float = 100_000.0
    max_open_positions: int = 10
    daily_loss_cap: float = 2_000.0
    kill_switch_enabled: bool = False

    cash: float = field(init=False)
    submitted_orders: list[Order] = field(default_factory=list)
    filled_orders: list[Fill] = field(default_factory=list)
    canceled_orders: list[Order] = field(default_factory=list)
    rejected_orders: list[Order] = field(default_factory=list)
    positions: dict[str, Position] = field(default_factory=dict)
    day_start_equity: float = field(init=False)
    _current_day: pd.Timestamp | None = field(default=None, init=False, repr=False)
    _peak_equity: float = field(init=False, repr=False)
    _last_prices: dict[str, float] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate runtime configuration and initialize state."""
        if self.starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        if self.max_notional_per_trade <= 0:
            raise ValueError("max_notional_per_trade must be positive")
        if self.max_open_positions <= 0:
            raise ValueError("max_open_positions must be positive")
        if self.daily_loss_cap <= 0:
            raise ValueError("daily_loss_cap must be positive")

        self.cash = self.starting_cash
        self.day_start_equity = self.starting_cash
        self._peak_equity = self.starting_cash

    def submit_order(self, order: Order) -> Order:
        """Submit paper order, enforce safety/risk, and fill when approved."""
        self.submitted_orders.append(order)
        side = order.side.upper()
        LOGGER.info(
            "order_submitted order_id=%s symbol=%s side=%s qty=%.6f price=%.6f",
            order.order_id,
            order.symbol,
            side,
            order.quantity,
            order.price,
        )

        if not self.paper_trading_enabled:
            return self._reject(order, "paper_trading_disabled")
        if self.kill_switch_enabled or self.risk_manager.kill_switch_enabled:
            self.kill_switch_enabled = True
            return self._reject(order, "kill_switch_enabled")
        if not order.symbol.strip():
            return self._reject(order, "empty_symbol")
        if side not in {"BUY", "SELL"}:
            return self._reject(order, "invalid_side")
        if order.quantity <= 0:
            return self._reject(order, "non_positive_quantity")
        if order.price <= 0:
            return self._reject(order, "non_positive_price")

        self._update_day_anchor(order.timestamp)
        notional = order.quantity * order.price
        if notional > self.max_notional_per_trade:
            return self._reject(order, "max_notional_per_trade_exceeded")

        if side == "BUY":
            active_positions = sum(1 for position in self.positions.values() if position.quantity > 0)
            current_position = self.positions.get(order.symbol)
            is_new_position = current_position is None or current_position.quantity == 0
            if is_new_position and active_positions >= self.max_open_positions:
                return self._reject(order, "max_open_positions_exceeded")

        portfolio_state = self._build_portfolio_state()
        decision = self.risk_manager.validate_order(
            OrderRiskRequest(
                symbol=order.symbol,
                side=side,
                quantity=order.quantity,
                price=order.price,
                timestamp=order.timestamp,
                stop_loss_pct=order.stop_loss_pct,
                trailing_stop_pct=order.trailing_stop_pct,
            ),
            portfolio_state,
        )
        if not decision.approved:
            if decision.kill_switch_enabled:
                self.kill_switch_enabled = True
            return self._reject(order, *decision.reasons)

        fill = self.broker.execute(order)
        self._apply_fill(fill)
        order.status = ORDER_STATUS_FILLED
        self.filled_orders.append(fill)
        LOGGER.info(
            "order_filled order_id=%s symbol=%s side=%s qty=%.6f price=%.6f notional=%.2f",
            fill.order_id,
            fill.symbol,
            fill.side,
            fill.quantity,
            fill.price,
            fill.notional,
        )

        if self.current_equity() <= (self.day_start_equity - self.daily_loss_cap):
            self.kill_switch_enabled = True
            self.risk_manager.kill_switch_enabled = True
            self.risk_manager.kill_switch_triggered_at = order.timestamp
            LOGGER.warning(
                "kill_switch_triggered reason=daily_loss_cap_breached equity=%.2f day_start_equity=%.2f cap=%.2f",
                self.current_equity(),
                self.day_start_equity,
                self.daily_loss_cap,
            )

        return order

    def cancel_order(self, order_id: str) -> Order | None:
        """Cancel a submitted-but-unfilled order."""
        for order in self.submitted_orders:
            if order.order_id == order_id and order.status == ORDER_STATUS_SUBMITTED:
                order.status = ORDER_STATUS_CANCELED
                self.canceled_orders.append(order)
                LOGGER.info("order_canceled order_id=%s", order_id)
                return order
        return None

    def mark_to_market(self, prices: dict[str, float]) -> float:
        """Update unrealized PnL using provided mark prices."""
        for symbol, price in prices.items():
            if symbol in self.positions and price > 0:
                self._last_prices[symbol] = price

        total_unrealized = 0.0
        for symbol, position in self.positions.items():
            mark_price = self._last_prices.get(symbol, position.avg_price)
            position.unrealized_pnl = (mark_price - position.avg_price) * position.quantity
            total_unrealized += position.unrealized_pnl
        return float(total_unrealized)

    def current_equity(self) -> float:
        """Return current equity from cash + marked position value."""
        position_value = 0.0
        for symbol, position in self.positions.items():
            mark_price = self._last_prices.get(symbol, position.avg_price)
            position_value += position.quantity * mark_price
        equity = self.cash + position_value
        self._peak_equity = max(self._peak_equity, equity)
        return float(equity)

    def realized_pnl(self) -> float:
        """Return total realized PnL across positions."""
        return float(sum(position.realized_pnl for position in self.positions.values()))

    def unrealized_pnl(self) -> float:
        """Return total unrealized PnL across positions."""
        return float(sum(position.unrealized_pnl for position in self.positions.values()))

    def export_trades(self, path: str | Path) -> Path:
        """Export filled trades to CSV for auditability."""
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)

        rows = [asdict(fill) for fill in self.filled_orders]
        frame = pd.DataFrame(rows)
        if frame.empty:
            frame = pd.DataFrame(
                columns=[
                    "order_id",
                    "symbol",
                    "side",
                    "quantity",
                    "price",
                    "timestamp",
                    "notional",
                ]
            )
        frame.to_csv(output, index=False)
        return output.resolve()

    def restore_state(
        self,
        cash: float,
        day_start_equity: float,
        peak_equity: float,
        positions: dict[str, Position],
        kill_switch_enabled: bool = False,
    ) -> None:
        """Restore executor state from a persisted snapshot."""
        self.cash = float(cash)
        self.day_start_equity = float(day_start_equity)
        self._peak_equity = float(peak_equity)
        self.positions = {
            symbol: Position(
                symbol=position.symbol,
                quantity=float(position.quantity),
                avg_price=float(position.avg_price),
                realized_pnl=float(position.realized_pnl),
                unrealized_pnl=float(position.unrealized_pnl),
            )
            for symbol, position in positions.items()
        }
        self._last_prices = {
            symbol: float(position.avg_price)
            for symbol, position in self.positions.items()
            if position.quantity > 0
        }
        self.kill_switch_enabled = bool(kill_switch_enabled)

    def snapshot_state(self) -> tuple[float, float, float, dict[str, Position]]:
        """Return current portfolio state for durable persistence."""
        snapshot_positions = {
            symbol: Position(
                symbol=position.symbol,
                quantity=float(position.quantity),
                avg_price=float(position.avg_price),
                realized_pnl=float(position.realized_pnl),
                unrealized_pnl=float(position.unrealized_pnl),
            )
            for symbol, position in self.positions.items()
            if position.quantity > 0
        }
        return (
            float(self.cash),
            float(self.day_start_equity),
            float(self._peak_equity),
            snapshot_positions,
        )

    def _reject(self, order: Order, *reasons: str) -> Order:
        """Mark order as rejected with reasons."""
        order.status = ORDER_STATUS_REJECTED
        order.rejection_reasons = tuple(sorted(set(reasons)))
        self.rejected_orders.append(order)
        LOGGER.warning(
            "order_rejected order_id=%s symbol=%s reasons=%s",
            order.order_id,
            order.symbol,
            ",".join(order.rejection_reasons),
        )
        return order

    def _update_day_anchor(self, timestamp: pd.Timestamp) -> None:
        """Reset day-level anchor for daily loss checks on date change."""
        order_day = pd.Timestamp(timestamp.normalize())
        if self._current_day is None or order_day != self._current_day:
            self._current_day = order_day
            self.day_start_equity = self.current_equity()

    def _apply_fill(self, fill: Fill) -> None:
        """Apply fill to cash and position ledger."""
        side = fill.side.upper()
        self._last_prices[fill.symbol] = fill.price
        position = self.positions.get(fill.symbol)
        if position is None:
            position = Position(symbol=fill.symbol)
            self.positions[fill.symbol] = position

        if side == "BUY":
            total_cost = fill.quantity * fill.price
            self.cash -= total_cost
            total_quantity = position.quantity + fill.quantity
            if total_quantity > 0:
                position.avg_price = (
                    (position.quantity * position.avg_price) + total_cost
                ) / total_quantity
            position.quantity = total_quantity
        else:
            close_quantity = min(fill.quantity, position.quantity)
            proceeds = close_quantity * fill.price
            self.cash += proceeds
            position.realized_pnl += (fill.price - position.avg_price) * close_quantity
            position.quantity -= close_quantity
            if position.quantity <= 0:
                position.quantity = 0.0
                position.avg_price = 0.0

        position.unrealized_pnl = (fill.price - position.avg_price) * position.quantity

    def _build_portfolio_state(self) -> PortfolioRiskState:
        """Build risk state snapshot for order validation."""
        open_positions = {
            symbol: abs(position.quantity * self._last_prices.get(symbol, position.avg_price))
            for symbol, position in self.positions.items()
            if position.quantity > 0
        }
        gross_exposure = float(sum(open_positions.values()))

        return PortfolioRiskState(
            equity=self.current_equity(),
            day_start_equity=self.day_start_equity,
            peak_equity=self._peak_equity,
            gross_exposure=gross_exposure,
            open_positions=open_positions,
        )
