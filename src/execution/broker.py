"""Paper broker abstraction and simulated implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.execution.models import Fill, Order


class PaperBroker(ABC):
    """Abstract paper broker interface."""

    @abstractmethod
    def execute(self, order: Order) -> Fill:
        """Execute order and return a simulated fill."""
        raise NotImplementedError


@dataclass(slots=True)
class SimulatedPaperBroker(PaperBroker):
    """Simple immediate-fill paper broker."""

    def execute(self, order: Order) -> Fill:
        """Fill at requested limit/market proxy price."""
        return Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side.upper(),
            quantity=order.quantity,
            price=order.price,
            timestamp=order.timestamp,
            notional=order.quantity * order.price,
        )
