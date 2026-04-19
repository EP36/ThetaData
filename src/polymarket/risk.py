"""Risk guard — seven ordered checks that must all pass before execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.polymarket.config import PolymarketConfig
from src.polymarket.opportunities import Opportunity
from src.polymarket.positions import PositionsLedger

LOGGER = logging.getLogger("theta.polymarket.risk")

_CONFIDENCE_SCORE: dict[str, float] = {
    "low": 0.0,
    "medium": 0.5,
    "high": 1.0,
}
_MIN_CONFIDENCE_SCORE = 0.5


@dataclass(slots=True)
class RiskGuard:
    """Evaluates seven ordered risk checks before any order is placed.

    All checks must pass; the first failure short-circuits.
    Never raises for a failed check — logs and returns (False, reason).
    """

    config: PolymarketConfig
    ledger: PositionsLedger
    _paused: bool = field(default=False, repr=False)

    def pause(self) -> None:
        """Pause the bot — blocks all execution until resume() is called."""
        self._paused = True
        LOGGER.warning("polymarket_risk_bot_paused")

    def resume(self) -> None:
        """Resume execution after a pause."""
        self._paused = False
        LOGGER.info("polymarket_risk_bot_resumed")

    @property
    def is_paused(self) -> bool:
        return self._paused

    def check(
        self, opportunity: Opportunity, proposed_size_usdc: float
    ) -> tuple[bool, str]:
        """Run all risk checks in order. Returns (passed, reason_string).

        Checks:
          1. Bot is not paused
          2. edge_pct >= min_edge_pct
          3. confidence score >= 0.5
          4. proposed_size_usdc <= max_trade_usdc
          5. open positions < max_positions
          6. daily P&L has not breached -daily_loss_limit
          7. market volume_24h > min_volume_24h
        """
        # 1 — pause flag
        if self._paused:
            reason = "bot_paused"
            LOGGER.info(
                "polymarket_risk_fail check=pause reason=%s strategy=%s",
                reason,
                opportunity.strategy,
            )
            return False, reason

        # 2 — minimum edge
        if opportunity.edge_pct < self.config.min_edge_pct:
            reason = (
                f"edge_pct={opportunity.edge_pct:.4f} "
                f"< min={self.config.min_edge_pct}"
            )
            LOGGER.info(
                "polymarket_risk_fail check=edge reason=%s strategy=%s",
                reason,
                opportunity.strategy,
            )
            return False, reason

        # 3 — confidence threshold
        conf_score = _CONFIDENCE_SCORE.get(opportunity.confidence, 0.0)
        if conf_score < _MIN_CONFIDENCE_SCORE:
            reason = (
                f"confidence={opportunity.confidence} "
                f"score={conf_score} < {_MIN_CONFIDENCE_SCORE}"
            )
            LOGGER.info(
                "polymarket_risk_fail check=confidence reason=%s strategy=%s",
                reason,
                opportunity.strategy,
            )
            return False, reason

        # 4 — trade size
        if proposed_size_usdc > self.config.max_trade_usdc:
            reason = (
                f"proposed_size={proposed_size_usdc:.2f} "
                f"> max={self.config.max_trade_usdc}"
            )
            LOGGER.info(
                "polymarket_risk_fail check=size reason=%s strategy=%s",
                reason,
                opportunity.strategy,
            )
            return False, reason

        # 5 — open position count
        open_count = self.ledger.open_count()
        if open_count >= self.config.max_positions:
            reason = (
                f"open_positions={open_count} "
                f">= max={self.config.max_positions}"
            )
            LOGGER.info(
                "polymarket_risk_fail check=positions reason=%s strategy=%s",
                reason,
                opportunity.strategy,
            )
            return False, reason

        # 6 — daily loss limit
        daily_pnl = self.ledger.daily_pnl()
        if daily_pnl <= -self.config.daily_loss_limit:
            reason = (
                f"daily_pnl={daily_pnl:.2f} "
                f"<= -limit={-self.config.daily_loss_limit}"
            )
            LOGGER.info(
                "polymarket_risk_fail check=daily_loss reason=%s strategy=%s",
                reason,
                opportunity.strategy,
            )
            return False, reason

        # 7 — market liquidity (volume)
        if opportunity.volume_24h <= self.config.min_volume_24h:
            reason = (
                f"volume_24h={opportunity.volume_24h:.0f} "
                f"<= min={self.config.min_volume_24h:.0f}"
            )
            LOGGER.info(
                "polymarket_risk_fail check=volume reason=%s strategy=%s",
                reason,
                opportunity.strategy,
            )
            return False, reason

        LOGGER.info(
            "polymarket_risk_pass strategy=%s edge_pct=%.4f size_usdc=%.2f",
            opportunity.strategy,
            opportunity.edge_pct,
            proposed_size_usdc,
        )
        return True, "all_checks_passed"
