"""Deterministic rule-based strategy selection and allocation logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.selection.regime import RegimeClassification

EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class SelectionConfig:
    """Configuration for eligibility gates, scoring, and allocation."""

    max_recent_drawdown: float = 0.20
    min_recent_expectancy: float = 0.0
    min_recent_trades: int = 5
    min_score_threshold: float = 0.05
    mediocre_score_threshold: float = 0.20
    mediocre_size_multiplier: float = 0.50
    top_n: int = 1


@dataclass(frozen=True, slots=True)
class GlobalSelectionState:
    """Global risk and execution gates that apply to all strategies."""

    kill_switch_enabled: bool
    paper_trading_enabled: bool
    worker_enable_trading: bool
    risk_budget_available: bool
    max_positions_breached: bool


@dataclass(frozen=True, slots=True)
class StrategyCandidate:
    """Normalized per-strategy inputs for eligibility and scoring."""

    strategy: str
    enabled: bool
    signal: float
    recent_expectancy: float
    recent_sharpe: float
    recent_win_rate: float
    recent_drawdown: float
    recent_trades: int
    required_data_available: bool
    compatible_regimes: tuple[str, ...]
    signal_confidence: float = 0.0
    external_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StrategyScore:
    """Eligibility + score output for one strategy."""

    strategy: str
    signal: float
    eligible: bool
    reasons: tuple[str, ...]
    score: float
    recent_expectancy: float
    recent_sharpe: float
    win_rate: float
    drawdown_penalty: float
    regime_fit: float
    sizing_multiplier: float


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    """Final selection decision and candidate diagnostics."""

    selected_strategy: str | None
    selected_score: float
    sizing_multiplier: float
    allocation_fraction: float
    minimum_score_threshold: float
    regime: str
    regime_signals: dict[str, float]
    candidates: tuple[StrategyScore, ...]

    def as_dict(self) -> dict[str, Any]:
        """Serialize decision for storage or API payloads."""
        return {
            "selected_strategy": self.selected_strategy,
            "selected_score": float(self.selected_score),
            "sizing_multiplier": float(self.sizing_multiplier),
            "allocation_fraction": float(self.allocation_fraction),
            "minimum_score_threshold": float(self.minimum_score_threshold),
            "regime": self.regime,
            "regime_signals": dict(self.regime_signals),
            "candidates": [
                {
                    "strategy": item.strategy,
                    "signal": float(item.signal),
                    "eligible": bool(item.eligible),
                    "reasons": list(item.reasons),
                    "score": float(item.score),
                    "recent_expectancy": float(item.recent_expectancy),
                    "recent_sharpe": float(item.recent_sharpe),
                    "win_rate": float(item.win_rate),
                    "drawdown_penalty": float(item.drawdown_penalty),
                    "regime_fit": float(item.regime_fit),
                    "sizing_multiplier": float(item.sizing_multiplier),
                }
                for item in self.candidates
            ],
        }


class StrategySelector:
    """Evaluate eligibility, score candidates, and select deterministic top strategy."""

    def __init__(self, config: SelectionConfig | None = None) -> None:
        self.config = config or SelectionConfig()

    def select(
        self,
        regime: RegimeClassification,
        candidates: list[StrategyCandidate],
        global_state: GlobalSelectionState,
    ) -> SelectionDecision:
        """Select a strategy using deterministic gates and scoring rules."""
        scored: list[StrategyScore] = []
        for candidate in candidates:
            scored.append(self._evaluate_candidate(candidate, regime, global_state))

        ranked = sorted(
            scored,
            key=lambda item: (
                -item.score,
                item.strategy,
            ),
        )

        qualified = [
            item
            for item in ranked
            if item.eligible
            and item.signal > EPSILON
            and item.score >= self.config.min_score_threshold
        ]

        selected = qualified[0] if qualified else None
        if selected is None:
            return SelectionDecision(
                selected_strategy=None,
                selected_score=0.0,
                sizing_multiplier=0.0,
                allocation_fraction=0.0,
                minimum_score_threshold=self.config.min_score_threshold,
                regime=regime.state,
                regime_signals=regime.as_signals(),
                candidates=tuple(ranked),
            )

        return SelectionDecision(
            selected_strategy=selected.strategy,
            selected_score=float(selected.score),
            sizing_multiplier=float(selected.sizing_multiplier),
            allocation_fraction=float(selected.sizing_multiplier),
            minimum_score_threshold=self.config.min_score_threshold,
            regime=regime.state,
            regime_signals=regime.as_signals(),
            candidates=tuple(ranked),
        )

    def _evaluate_candidate(
        self,
        candidate: StrategyCandidate,
        regime: RegimeClassification,
        global_state: GlobalSelectionState,
    ) -> StrategyScore:
        """Evaluate eligibility gates and compute score for one strategy."""
        reasons: list[str] = []

        if not candidate.enabled:
            reasons.append("strategy_disabled")
        for reason in candidate.external_reasons:
            if reason.strip():
                reasons.append(reason.strip())
        if global_state.kill_switch_enabled:
            reasons.append("kill_switch_enabled")
        if not global_state.paper_trading_enabled:
            reasons.append("paper_trading_disabled")
        if not global_state.worker_enable_trading:
            reasons.append("worker_trading_disabled")
        if not candidate.required_data_available:
            reasons.append("required_market_data_missing")
        if candidate.recent_trades < self.config.min_recent_trades:
            reasons.append("insufficient_recent_trades")
        if candidate.recent_drawdown > self.config.max_recent_drawdown:
            reasons.append("recent_drawdown_exceeded")
        if candidate.recent_expectancy < self.config.min_recent_expectancy:
            reasons.append("recent_expectancy_below_threshold")
        if not global_state.risk_budget_available:
            reasons.append("insufficient_risk_budget")
        if global_state.max_positions_breached:
            reasons.append("max_open_positions_breached")
        if candidate.signal <= EPSILON:
            reasons.append("no_active_signal")

        regime_fit = self._regime_fit(candidate.compatible_regimes, regime.state)
        if regime_fit < 0.5:
            reasons.append("regime_incompatible")

        drawdown_penalty = min(max(candidate.recent_drawdown, 0.0), 1.0)
        score = (
            (candidate.recent_expectancy * 0.35)
            + (candidate.recent_sharpe * 0.25)
            + (candidate.recent_win_rate * 0.15)
            + (regime_fit * 0.15)
            - (drawdown_penalty * 0.10)
            + (candidate.signal_confidence * 0.0)
        )

        eligible = len(reasons) == 0
        sizing_multiplier = (
            self.config.mediocre_size_multiplier
            if score < self.config.mediocre_score_threshold
            else 1.0
        )

        if eligible and score < self.config.min_score_threshold:
            eligible = False
            reasons.append("score_below_threshold")

        return StrategyScore(
            strategy=candidate.strategy,
            signal=float(candidate.signal),
            eligible=eligible,
            reasons=tuple(sorted(set(reasons))),
            score=float(score),
            recent_expectancy=float(candidate.recent_expectancy),
            recent_sharpe=float(candidate.recent_sharpe),
            win_rate=float(candidate.recent_win_rate),
            drawdown_penalty=float(drawdown_penalty),
            regime_fit=float(regime_fit),
            sizing_multiplier=float(sizing_multiplier),
        )

    @staticmethod
    def _regime_fit(compatible_regimes: tuple[str, ...], regime: str) -> float:
        """Compute strategy/regime fit score in [0, 1]."""
        compat = {item.strip().lower() for item in compatible_regimes if item.strip()}
        regime_key = regime.strip().lower()

        if regime_key in compat:
            return 1.0
        if regime_key == "neutral" and "neutral" in compat:
            return 1.0
        if regime_key == "neutral":
            return 0.6
        if "neutral" in compat:
            return 0.55
        return 0.2


DEFAULT_STRATEGY_REGIME_COMPATIBILITY: dict[str, tuple[str, ...]] = {
    "moving_average_crossover": ("trending", "neutral"),
    "breakout_momentum": ("trending",),
    "rsi_mean_reversion": ("mean_reverting", "neutral"),
    "vwap_mean_reversion": ("mean_reverting",),
}


def strategy_compatible_regimes(strategy_name: str) -> tuple[str, ...]:
    """Return default compatible regimes for one strategy."""
    return DEFAULT_STRATEGY_REGIME_COMPATIBILITY.get(strategy_name, ("neutral",))
