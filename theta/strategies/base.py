"""Common interfaces for all theta strategies.

Every strategy must conform to the Strategy Protocol: implement a `name`
property, an `evaluate_opportunity(now)` method that returns either a
PlannedTrade or None, and an `execute(planned, dry_run)` method that
returns an ExecutionResult.

The separation keeps signal generation (evaluate) and order submission
(execute) independent, which makes dry-run, backtesting, and unit-testing
straightforward.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------

@dataclass
class PlannedTrade:
    """Everything needed to execute a trade, produced by Strategy.evaluate_opportunity."""
    strategy_name: str
    exchange: str                         # "coinbase", "hyperliquid", …
    product_id: str                       # e.g. "ETH-USD", "ETH/USD:USDC"
    side: Literal["buy", "sell"]
    notional_usd: float
    expected_edge_bps: float              # alpha estimate above round-trip costs
    score: float = 0.0                    # filled by runner before execution
    notes: str = ""                       # human-readable signal explanation


@dataclass
class ExecutionResult:
    """Outcome of Strategy.execute."""
    success: bool
    strategy_name: str
    order_id: str = ""
    client_order_id: str = ""
    notional_usd: float = 0.0
    realized_edge_bps: float = 0.0       # 0 until fill is confirmed via polling
    dry_run: bool = False
    error: str = ""


# ---------------------------------------------------------------------------
# Strategy Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Strategy(Protocol):
    """Duck-typed interface every theta strategy must satisfy.

    Implementors do NOT need to inherit from this class — Protocol matching
    is structural (duck-typed).  Use `isinstance(obj, Strategy)` to verify.
    """

    @property
    def name(self) -> str:
        """Short human-readable strategy identifier (used in logs and records)."""
        ...

    def evaluate_opportunity(self, now: datetime) -> Optional[PlannedTrade]:
        """Assess current market conditions and return a trade proposal or None.

        Must be side-effect free except for I/O (market data fetches).
        Must NOT submit orders.  Returns None if no trade is warranted.
        """
        ...

    def execute(
        self,
        planned: PlannedTrade,
        dry_run: bool = False,
    ) -> ExecutionResult:
        """Submit the trade described by `planned`.

        If dry_run=True, build and log the full record but do not send orders.
        Must always return an ExecutionResult (never raise for user-facing errors).
        """
        ...
