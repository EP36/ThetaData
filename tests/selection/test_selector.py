"""Tests for deterministic strategy selection and scoring."""

from __future__ import annotations

from src.selection.regime import RegimeClassification
from src.selection.selector import (
    GlobalSelectionState,
    SelectionConfig,
    StrategyCandidate,
    StrategySelector,
)


def _regime(state: str = "trending") -> RegimeClassification:
    return RegimeClassification(
        state=state,  # type: ignore[arg-type]
        moving_average_slope=0.01,
        price_vs_moving_average=0.02,
        atr_pct=0.01,
        directional_persistence=0.6,
    )


def _global_state() -> GlobalSelectionState:
    return GlobalSelectionState(
        kill_switch_enabled=False,
        paper_trading_enabled=True,
        worker_enable_trading=True,
        risk_budget_available=True,
        max_positions_breached=False,
    )


def test_eligibility_gate_blocks_disabled_strategy() -> None:
    selector = StrategySelector(SelectionConfig(min_recent_trades=1, min_score_threshold=-1.0))
    decision = selector.select(
        regime=_regime("trending"),
        global_state=_global_state(),
        candidates=[
            StrategyCandidate(
                strategy="moving_average_crossover",
                enabled=False,
                signal=1.0,
                recent_expectancy=0.2,
                recent_sharpe=0.5,
                recent_win_rate=0.6,
                recent_drawdown=0.05,
                recent_trades=10,
                required_data_available=True,
                compatible_regimes=("trending",),
            )
        ],
    )
    assert decision.selected_strategy is None
    assert "strategy_disabled" in decision.candidates[0].reasons


def test_highest_scoring_strategy_is_selected() -> None:
    selector = StrategySelector(SelectionConfig(min_recent_trades=1, min_score_threshold=0.0))
    decision = selector.select(
        regime=_regime("trending"),
        global_state=_global_state(),
        candidates=[
            StrategyCandidate(
                strategy="moving_average_crossover",
                enabled=True,
                signal=1.0,
                recent_expectancy=0.20,
                recent_sharpe=0.50,
                recent_win_rate=0.60,
                recent_drawdown=0.05,
                recent_trades=20,
                required_data_available=True,
                compatible_regimes=("trending",),
            ),
            StrategyCandidate(
                strategy="breakout_momentum",
                enabled=True,
                signal=1.0,
                recent_expectancy=0.35,
                recent_sharpe=0.75,
                recent_win_rate=0.62,
                recent_drawdown=0.04,
                recent_trades=20,
                required_data_available=True,
                compatible_regimes=("trending",),
            ),
        ],
    )
    assert decision.selected_strategy == "breakout_momentum"


def test_tie_break_uses_strategy_name_order() -> None:
    selector = StrategySelector(SelectionConfig(min_recent_trades=1, min_score_threshold=0.0))
    candidates = [
        StrategyCandidate(
            strategy="zeta_strategy",
            enabled=True,
            signal=1.0,
            recent_expectancy=0.2,
            recent_sharpe=0.4,
            recent_win_rate=0.6,
            recent_drawdown=0.05,
            recent_trades=10,
            required_data_available=True,
            compatible_regimes=("trending",),
        ),
        StrategyCandidate(
            strategy="alpha_strategy",
            enabled=True,
            signal=1.0,
            recent_expectancy=0.2,
            recent_sharpe=0.4,
            recent_win_rate=0.6,
            recent_drawdown=0.05,
            recent_trades=10,
            required_data_available=True,
            compatible_regimes=("trending",),
        ),
    ]

    decision = selector.select(
        regime=_regime("trending"),
        global_state=_global_state(),
        candidates=candidates,
    )

    assert decision.selected_strategy == "alpha_strategy"


def test_mediocre_score_gets_reduced_sizing() -> None:
    selector = StrategySelector(
        SelectionConfig(
            min_recent_trades=1,
            min_score_threshold=0.0,
            mediocre_score_threshold=0.20,
            mediocre_size_multiplier=0.5,
        )
    )
    decision = selector.select(
        regime=_regime("neutral"),
        global_state=_global_state(),
        candidates=[
            StrategyCandidate(
                strategy="rsi_mean_reversion",
                enabled=True,
                signal=1.0,
                recent_expectancy=0.02,
                recent_sharpe=0.05,
                recent_win_rate=0.51,
                recent_drawdown=0.03,
                recent_trades=12,
                required_data_available=True,
                compatible_regimes=("mean_reverting",),
            )
        ],
    )
    assert decision.selected_strategy == "rsi_mean_reversion"
    assert decision.sizing_multiplier == 0.5


def test_no_eligible_strategy_results_in_no_trade() -> None:
    selector = StrategySelector(SelectionConfig(min_recent_trades=5, min_score_threshold=0.0))
    decision = selector.select(
        regime=_regime("trending"),
        global_state=_global_state(),
        candidates=[
            StrategyCandidate(
                strategy="moving_average_crossover",
                enabled=True,
                signal=0.0,
                recent_expectancy=0.2,
                recent_sharpe=0.4,
                recent_win_rate=0.55,
                recent_drawdown=0.05,
                recent_trades=10,
                required_data_available=True,
                compatible_regimes=("trending",),
            )
        ],
    )
    assert decision.selected_strategy is None
    assert decision.allocation_fraction == 0.0


def test_external_reasons_force_ineligibility() -> None:
    selector = StrategySelector(SelectionConfig(min_recent_trades=1, min_score_threshold=0.0))
    decision = selector.select(
        regime=_regime("trending"),
        global_state=_global_state(),
        candidates=[
            StrategyCandidate(
                strategy="breakout_momentum",
                enabled=True,
                signal=1.0,
                recent_expectancy=0.4,
                recent_sharpe=0.8,
                recent_win_rate=0.65,
                recent_drawdown=0.04,
                recent_trades=20,
                required_data_available=True,
                compatible_regimes=("trending",),
                external_reasons=("symbol_locked_by_active_strategy:moving_average_crossover",),
            )
        ],
    )
    assert decision.selected_strategy is None
    assert (
        "symbol_locked_by_active_strategy:moving_average_crossover"
        in decision.candidates[0].reasons
    )
