"""PortfolioAllocator — multi-strategy trade selection with conflict prevention.

Given a list of approved PlannedTrade proposals (already past global risk limits),
the allocator selects which trades to actually execute each tick.

Selection modes:
  single_best              — execute only the highest-scoring trade
  priority_with_fallback   — execute best; also execute second if it passes all gates
  proportional_split       — currently an alias for priority_with_fallback

Gates (checked in order for each candidate beyond the primary):
  1. Score >= fallback_min_score
  2. Remaining capital >= candidate.notional_usd
  3. No direction conflict with already-selected trades (opposing side, same asset)
  4. Portfolio ETH buy notional stays under max_eth_exposure_usd (when > 0)

Composite score formula:
  score = edge_weight × expected_edge_bps
        + confidence_weight × (confidence × 100)
        − risk_penalty_weight × (risk_score × 100)

Env vars (read by runner_worker, not here):
  STRATEGY_SELECTION_MODE           str    default=priority_with_fallback
  PORTFOLIO_AVAILABLE_CAPITAL_USD   float  default=500.0
  PORTFOLIO_MAX_ETH_EXPOSURE_USD    float  default=0.0  (0 = disabled)
  PORTFOLIO_FALLBACK_MIN_SCORE      float  default=10.0
  PORTFOLIO_COOLDOWN_SECONDS        int    default=0    (0 = disabled)
  ALLOCATOR_EDGE_WEIGHT             float  default=1.0
  ALLOCATOR_CONFIDENCE_WEIGHT       float  default=0.0
  ALLOCATOR_RISK_PENALTY_WEIGHT     float  default=0.0
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from theta.strategies.base import PlannedTrade

LOGGER = logging.getLogger("theta.orchestration.allocator")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class AllocatorConfig:
    mode: str = "priority_with_fallback"
    available_capital_usd: float = 500.0
    max_eth_exposure_usd: float = 0.0      # 0 = disabled
    fallback_min_score: float = 10.0       # minimum score to allow a non-primary trade
    cooldown_seconds: int = 0              # 0 = disabled
    edge_weight: float = 1.0
    confidence_weight: float = 0.0
    risk_penalty_weight: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _asset_from_product(product_id: str) -> str:
    """Extract base asset symbol — 'ETH-USD' → 'ETH', 'ETH/USD:USDC' → 'ETH'."""
    return product_id.replace("/", "-").split("-")[0].upper()


def _are_conflicting(a: "PlannedTrade", b: "PlannedTrade") -> bool:
    """True if a and b take opposing positions on the same asset."""
    if _asset_from_product(a.product_id) != _asset_from_product(b.product_id):
        return False
    return a.side != b.side


# ---------------------------------------------------------------------------
# Allocator
# ---------------------------------------------------------------------------

class PortfolioAllocator:
    """Select which approved proposals to execute each tick."""

    def __init__(self, config: AllocatorConfig | None = None) -> None:
        self._cfg = config or AllocatorConfig()
        self._cooldowns: dict[str, datetime] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def composite_score(self, trade: "PlannedTrade") -> float:
        c = self._cfg
        return (
            c.edge_weight * trade.expected_edge_bps
            + c.confidence_weight * (trade.confidence * 100.0)
            - c.risk_penalty_weight * (trade.risk_score * 100.0)
        )

    def select(self, proposals: list["PlannedTrade"]) -> list["PlannedTrade"]:
        """Score, filter, and return the trades to execute this tick."""
        if not proposals:
            return []

        for t in proposals:
            t.score = self.composite_score(t)
            LOGGER.debug(
                "allocator score strategy=%s score=%.2f "
                "edge=%.1f confidence=%.2f risk=%.2f",
                t.strategy_name, t.score,
                t.expected_edge_bps, t.confidence, t.risk_score,
            )

        ranked = sorted(proposals, key=lambda t: t.score, reverse=True)

        now = datetime.now(timezone.utc)
        eligible: list["PlannedTrade"] = []
        for t in ranked:
            last = self._cooldowns.get(t.strategy_name)
            if last is not None and self._cfg.cooldown_seconds > 0:
                elapsed = (now - last).total_seconds()
                if elapsed < self._cfg.cooldown_seconds:
                    LOGGER.info(
                        "allocator reject strategy=%s reason=cooldown "
                        "elapsed=%.0fs required=%ds",
                        t.strategy_name, elapsed, self._cfg.cooldown_seconds,
                    )
                    continue
            eligible.append(t)

        if not eligible:
            LOGGER.info("allocator decision=no_trade reason=all_in_cooldown")
            return []

        mode = self._cfg.mode
        if mode == "single_best":
            trade = eligible[0]
            LOGGER.info(
                "allocator mode=single_best selected=%s score=%.2f",
                trade.strategy_name, trade.score,
            )
            return [trade]
        elif mode in ("priority_with_fallback", "proportional_split"):
            return self._priority_with_fallback(eligible)
        else:
            LOGGER.warning(
                "allocator unknown_mode=%s — falling back to single_best", mode,
            )
            return [eligible[0]]

    def record_executed(self, strategy_name: str) -> None:
        """Record execution time for cooldown tracking."""
        self._cooldowns[strategy_name] = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _priority_with_fallback(
        self, eligible: list["PlannedTrade"]
    ) -> list["PlannedTrade"]:
        selected: list["PlannedTrade"] = []
        capital_used = 0.0
        eth_buy_notional = 0.0

        for i, candidate in enumerate(eligible):
            label = "primary" if i == 0 else "fallback"

            # Non-primary candidates must clear the fallback score threshold.
            if i > 0 and candidate.score < self._cfg.fallback_min_score:
                LOGGER.info(
                    "allocator reject strategy=%s label=%s "
                    "reason=below_fallback_threshold score=%.2f threshold=%.2f",
                    candidate.strategy_name, label,
                    candidate.score, self._cfg.fallback_min_score,
                )
                break  # list is ranked; nothing below will pass either

            # Capital check.
            remaining = self._cfg.available_capital_usd - capital_used
            if candidate.notional_usd > remaining:
                LOGGER.info(
                    "allocator reject strategy=%s label=%s "
                    "reason=insufficient_capital needed=%.2f remaining=%.2f",
                    candidate.strategy_name, label,
                    candidate.notional_usd, remaining,
                )
                if i == 0:
                    break  # primary can't fit — give up entirely
                continue

            # Direction conflict with already-selected trades.
            conflict = next(
                (s for s in selected if _are_conflicting(s, candidate)), None
            )
            if conflict is not None:
                LOGGER.info(
                    "allocator reject strategy=%s label=%s "
                    "reason=direction_conflict conflicts_with=%s "
                    "asset=%s selected_side=%s candidate_side=%s",
                    candidate.strategy_name, label,
                    conflict.strategy_name,
                    _asset_from_product(candidate.product_id),
                    conflict.side, candidate.side,
                )
                continue

            # Portfolio ETH exposure cap (buy trades only).
            if (
                self._cfg.max_eth_exposure_usd > 0
                and candidate.side == "buy"
                and _asset_from_product(candidate.product_id) == "ETH"
            ):
                projected = eth_buy_notional + candidate.notional_usd
                if projected > self._cfg.max_eth_exposure_usd:
                    LOGGER.info(
                        "allocator reject strategy=%s label=%s "
                        "reason=eth_exposure_cap projected=%.2f cap=%.2f",
                        candidate.strategy_name, label,
                        projected, self._cfg.max_eth_exposure_usd,
                    )
                    continue

            # Accepted.
            selected.append(candidate)
            capital_used += candidate.notional_usd
            if candidate.side == "buy" and _asset_from_product(candidate.product_id) == "ETH":
                eth_buy_notional += candidate.notional_usd

            LOGGER.info(
                "allocator select strategy=%s label=%s score=%.2f "
                "notional=%.2f capital_used=%.2f",
                candidate.strategy_name, label, candidate.score,
                candidate.notional_usd, capital_used,
            )

            if len(selected) >= 2:
                break

        return selected
