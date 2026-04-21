"""Combined portfolio state aggregating all brokers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from trauto.brokers.base import AccountSnapshot, Position

LOGGER = logging.getLogger("trauto.core.portfolio")


@dataclass
class PortfolioState:
    """Live snapshot of combined portfolio across all brokers."""

    accounts: dict[str, AccountSnapshot] = field(default_factory=dict)
    positions: dict[str, list[Position]] = field(default_factory=dict)

    @property
    def combined_value(self) -> float:
        return sum(a.portfolio_value for a in self.accounts.values())

    @property
    def combined_unrealized_pnl(self) -> float:
        return sum(a.unrealized_pnl for a in self.accounts.values())

    @property
    def combined_realized_today(self) -> float:
        return sum(a.realized_pnl_today for a in self.accounts.values())

    @property
    def total_open_positions(self) -> int:
        return sum(len(v) for v in self.positions.values())

    def all_positions(self) -> list[Position]:
        return [p for broker_positions in self.positions.values() for p in broker_positions]

    def to_dict(self) -> dict[str, Any]:
        return {
            "combined_value": round(self.combined_value, 2),
            "combined_unrealized_pnl": round(self.combined_unrealized_pnl, 2),
            "combined_realized_today": round(self.combined_realized_today, 4),
            "total_open_positions": self.total_open_positions,
            "by_broker": {
                broker: {
                    "cash": acc.cash,
                    "portfolio_value": acc.portfolio_value,
                    "buying_power": acc.buying_power,
                    "unrealized_pnl": acc.unrealized_pnl,
                    "realized_pnl_today": acc.realized_pnl_today,
                    "open_positions": len(self.positions.get(broker, [])),
                }
                for broker, acc in self.accounts.items()
            },
        }
