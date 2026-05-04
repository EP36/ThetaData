"""StrategyRunner — evaluate, rank, gate, and execute across strategies.

Each tick:
  1. Call evaluate_opportunity(now) on every registered strategy.
  2. Collect all non-None PlannedTrade proposals.
  3. Apply global risk limits (max notional per trade, daily budget per exchange).
  4. Hand approved proposals to PortfolioAllocator for scoring and selection.
  5. Execute each selected trade in order.
  6. Log every decision, regardless of outcome.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from theta.orchestration.allocator import PortfolioAllocator
    from theta.strategies.base import ExecutionResult, PlannedTrade, Strategy

LOGGER = logging.getLogger("theta.orchestration.runner")


# ---------------------------------------------------------------------------
# Risk limits
# ---------------------------------------------------------------------------

@dataclass
class GlobalRiskLimits:
    """Centralised per-run risk constraints.

    All monetary values are in USD.  Defaults are conservative; override
    via constructor or environment when you want to raise them.
    """
    # Hard cap on any single trade regardless of strategy config.
    max_notional_per_trade_usd: float = 500.0

    # Daily notional budget per exchange (key = exchange name, value = USD).
    # Entries are added automatically the first time an exchange is seen.
    max_daily_notional_per_exchange: dict[str, float] = field(
        default_factory=lambda: {
            "coinbase":    2_000.0,
            "hyperliquid":   500.0,
        }
    )

    # Minimum score (expected_edge_bps) required to trade.
    min_score_threshold: float = 0.0

    # TODO(risk): add max_open_positions, max_daily_loss_usd, drawdown_circuit_breaker


@dataclass
class _DailyNotional:
    """Tracks notional spent per exchange within the current UTC day."""
    date: date = field(default_factory=lambda: datetime.now(timezone.utc).date())
    spent: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    def _maybe_reset(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self.date:
            self.date = today
            self.spent = defaultdict(float)

    def can_spend(self, exchange: str, amount: float, limit: float) -> bool:
        self._maybe_reset()
        return self.spent[exchange] + amount <= limit

    def record(self, exchange: str, amount: float) -> None:
        self._maybe_reset()
        self.spent[exchange] += amount

    def remaining(self, exchange: str, limit: float) -> float:
        self._maybe_reset()
        return max(0.0, limit - self.spent[exchange])


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class StrategyRunner:
    """Orchestrates a collection of strategies through one tick or a loop."""

    def __init__(
        self,
        strategies: list["Strategy"],
        risk: GlobalRiskLimits | None = None,
        allocator: "PortfolioAllocator | None" = None,
    ) -> None:
        if not strategies:
            raise ValueError("at least one strategy is required")
        self._strategies = list(strategies)
        self._risk = risk or GlobalRiskLimits()
        self._daily = _DailyNotional()
        if allocator is None:
            from theta.orchestration.allocator import PortfolioAllocator
            self._allocator: "PortfolioAllocator" = PortfolioAllocator()
        else:
            self._allocator = allocator

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_once(self, dry_run: bool = False) -> "list[ExecutionResult]":
        """Run one full evaluate → rank → gate → execute tick.

        Returns a list of ExecutionResults for all trades attempted this tick
        (usually 0 or 1; up to 2 in priority_with_fallback mode).
        """
        from theta.strategies.base import ExecutionResult  # noqa: F401 (kept for TYPE_CHECKING)

        now = datetime.now(timezone.utc)
        LOGGER.info(
            "runner_tick time=%s strategies=%d dry_run=%s",
            now.isoformat(), len(self._strategies), dry_run,
        )

        # --- Evaluate all strategies ---
        proposals: list["PlannedTrade"] = []
        for strat in self._strategies:
            try:
                trade = strat.evaluate_opportunity(now)
            except Exception as exc:
                LOGGER.error(
                    "runner strategy=%s evaluate_error error=%s",
                    strat.name, exc,
                )
                continue

            if trade is None:
                LOGGER.info(
                    "runner strategy=%s evaluate=no_opportunity", strat.name,
                )
            else:
                LOGGER.info(
                    "runner strategy=%s evaluate=opportunity "
                    "product=%s side=%s notional=%.2f edge=%.1fbps",
                    strat.name, trade.product_id, trade.side,
                    trade.notional_usd, trade.expected_edge_bps,
                )
                proposals.append(trade)

        if not proposals:
            LOGGER.info("runner decision=no_trade reason=no_opportunities")
            return []

        # --- Apply global risk limits ---
        approved: list["PlannedTrade"] = []
        for trade in proposals:
            veto = self._check_risk(trade)
            if veto:
                LOGGER.info(
                    "runner strategy=%s vetoed reason=%s", trade.strategy_name, veto,
                )
            else:
                approved.append(trade)

        if not approved:
            LOGGER.info("runner decision=no_trade reason=all_proposals_vetoed")
            return []

        # --- Allocator: score, filter, select ---
        selected = self._allocator.select(approved)

        if not selected:
            LOGGER.info("runner decision=no_trade reason=allocator_selected_none")
            return []

        # Min-score gate (applied to primary trade only).
        if selected[0].score < self._risk.min_score_threshold:
            LOGGER.info(
                "runner decision=no_trade reason=below_min_score "
                "best_score=%.2f threshold=%.2f",
                selected[0].score, self._risk.min_score_threshold,
            )
            return []

        # --- Execute each selected trade ---
        results: list["ExecutionResult"] = []
        for trade in selected:
            LOGGER.info(
                "runner decision=execute strategy=%s product=%s side=%s "
                "notional=%.2f score=%.2f dry_run=%s",
                trade.strategy_name, trade.product_id, trade.side,
                trade.notional_usd, trade.score, dry_run,
            )

            executing_strategy = next(
                s for s in self._strategies if s.name == trade.strategy_name
            )
            result = executing_strategy.execute(trade, dry_run=dry_run)

            if not result.product_id:
                result.product_id = trade.product_id
            if not result.side:
                result.side = trade.side

            if result.success:
                if not dry_run:
                    self._daily.record(trade.exchange, trade.notional_usd)
                self._allocator.record_executed(trade.strategy_name)
                LOGGER.info(
                    "runner execute_result=success strategy=%s "
                    "order_id=%s client_order_id=%s notional=%.2f dry_run=%s",
                    result.strategy_name, result.order_id,
                    result.client_order_id, result.notional_usd, dry_run,
                )
            else:
                LOGGER.error(
                    "runner execute_result=failed strategy=%s error=%s",
                    result.strategy_name, result.error,
                )

            results.append(result)

        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_risk(self, trade: "PlannedTrade") -> str:
        """Return a veto reason string, or empty string if approved."""
        # 1. Per-trade notional cap.
        effective_notional = min(trade.notional_usd, self._risk.max_notional_per_trade_usd)
        if effective_notional < trade.notional_usd:
            # Cap it rather than reject — update in place.
            trade.notional_usd = effective_notional
            LOGGER.debug(
                "runner risk_cap strategy=%s notional capped to %.2f",
                trade.strategy_name, effective_notional,
            )

        # 2. Daily notional budget per exchange.
        daily_limit = self._risk.max_daily_notional_per_exchange.get(
            trade.exchange,
            self._risk.max_notional_per_trade_usd,  # conservative default
        )
        if not self._daily.can_spend(trade.exchange, trade.notional_usd, daily_limit):
            remaining = self._daily.remaining(trade.exchange, daily_limit)
            return (
                f"daily_notional_exceeded exchange={trade.exchange} "
                f"attempted={trade.notional_usd:.2f} remaining={remaining:.2f}"
            )

        # TODO(risk): max_open_positions check
        # TODO(risk): realized PnL drawdown circuit breaker

        return ""

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def strategy_names(self) -> list[str]:
        return [s.name for s in self._strategies]

    def daily_spent(self, exchange: str) -> float:
        return self._daily.spent.get(exchange, 0.0)
