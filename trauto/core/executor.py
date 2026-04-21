"""Unified order executor — routes approved signals to the correct broker."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from trauto.brokers.base import BrokerInterface, Order, OrderResult
from trauto.core.risk import GlobalRiskManager, RiskDecision

if TYPE_CHECKING:
    from trauto.core.portfolio import PortfolioState
    from trauto.strategies.base import BaseStrategy, Signal

LOGGER = logging.getLogger("trauto.core.executor")


@dataclass
class UnifiedExecutor:
    """Routes approved signals to broker adapters.

    The executor is the only component that calls broker.place_order().
    All signals must pass through GlobalRiskManager before reaching here.
    """

    risk_manager: GlobalRiskManager
    brokers: dict[str, BrokerInterface] = field(default_factory=dict)
    _pending_orders: list[dict[str, Any]] = field(default_factory=list, init=False)

    def register_broker(self, broker: BrokerInterface) -> None:
        self.brokers[broker.name] = broker
        LOGGER.info("executor_broker_registered broker=%s", broker.name)

    async def execute_signal(
        self,
        signal: "Signal",
        strategy: "BaseStrategy",
        portfolio: "PortfolioState",
    ) -> OrderResult | None:
        """Run risk check and execute the signal if approved.

        Returns:
            OrderResult if the order was attempted (real or dry_run),
            None if rejected by risk manager.
        """
        decision: RiskDecision = self.risk_manager.check(signal, strategy, portfolio)

        if not decision.approved:
            LOGGER.info(
                "signal_blocked strategy=%s symbol=%s reason=%s",
                signal.strategy_name,
                signal.symbol,
                decision.reason,
            )
            return None

        broker = self.brokers.get(signal.broker)
        if broker is None:
            LOGGER.error(
                "executor_no_broker signal_broker=%s known=%s",
                signal.broker,
                list(self.brokers),
            )
            return None

        action = signal.action.lower()
        if action not in ("buy", "sell", "close"):
            return None

        order = Order(
            symbol=signal.symbol,
            side="buy" if action == "buy" else "sell",
            quantity=signal.size_usd / signal.price if signal.price > 0 and signal.size_usd > 0 else 1.0,
            price=signal.price,
            client_order_id=f"{signal.strategy_name}_{signal.symbol}",
        )

        if decision.dry_run:
            LOGGER.info(
                "dry_run_signal strategy=%s broker=%s symbol=%s action=%s price=%.4f notes=%s",
                signal.strategy_name,
                signal.broker,
                signal.symbol,
                action,
                signal.price,
                signal.notes,
            )
            return OrderResult(
                broker=signal.broker,
                symbol=signal.symbol,
                side=order.side,
                quantity=order.quantity,
                price=order.price,
                order_id=f"dry_{signal.symbol}",
                status="dry_run",
            )

        try:
            result = await broker.place_order(order)
            if result.status in ("filled", "pending"):
                self.risk_manager.record_broker_success(signal.broker)
                LOGGER.info(
                    "order_placed strategy=%s broker=%s symbol=%s side=%s qty=%.4f price=%.4f status=%s",
                    signal.strategy_name,
                    signal.broker,
                    result.symbol,
                    result.side,
                    result.quantity,
                    result.price,
                    result.status,
                )
            else:
                LOGGER.warning(
                    "order_rejected strategy=%s broker=%s symbol=%s reason=%s",
                    signal.strategy_name,
                    signal.broker,
                    result.symbol,
                    result.rejection_reason,
                )
            return result
        except Exception as exc:
            LOGGER.error(
                "order_error strategy=%s broker=%s symbol=%s error=%s",
                signal.strategy_name,
                signal.broker,
                signal.symbol,
                exc,
            )
            self.risk_manager.record_broker_error(signal.broker)
            return None

    async def execute_batch(
        self,
        signals: list[tuple["Signal", "BaseStrategy"]],
        portfolio: "PortfolioState",
    ) -> list[OrderResult]:
        """Execute a batch of (signal, strategy) pairs, collecting results."""
        import asyncio
        tasks = [self.execute_signal(sig, strat, portfolio) for sig, strat in signals]
        results_raw = await asyncio.gather(*tasks, return_exceptions=False)
        return [r for r in results_raw if r is not None]
