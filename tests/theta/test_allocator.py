"""Unit tests for PortfolioAllocator — trade selection, conflict prevention, scoring.

Run directly:
    python -m tests.theta.test_allocator

Or with pytest (if the module path is resolved correctly):
    pytest tests/theta/test_allocator.py -v
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

from theta.orchestration.allocator import (
    AllocatorConfig,
    PortfolioAllocator,
    _are_conflicting,
    _asset_from_product,
)
from theta.strategies.base import ExecutionResult, PlannedTrade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trade(
    strategy: str = "s1",
    product: str = "ETH-USD",
    side: str = "buy",
    edge: float = 50.0,
    notional: float = 100.0,
    confidence: float = 1.0,
    risk_score: float = 0.0,
) -> PlannedTrade:
    return PlannedTrade(
        strategy_name=strategy,
        exchange="coinbase",
        product_id=product,
        side=side,
        notional_usd=notional,
        expected_edge_bps=edge,
        confidence=confidence,
        risk_score=risk_score,
    )


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def test_asset_from_product():
    assert _asset_from_product("ETH-USD") == "ETH"
    assert _asset_from_product("BTC-USD") == "BTC"
    assert _asset_from_product("ETH/USD:USDC") == "ETH"


def test_are_conflicting_opposite_sides():
    a = _trade("s1", product="ETH-USD", side="buy")
    b = _trade("s2", product="ETH-USD", side="sell")
    assert _are_conflicting(a, b) is True


def test_are_conflicting_same_side():
    a = _trade("s1", product="ETH-USD", side="buy")
    b = _trade("s2", product="ETH-USD", side="buy")
    assert _are_conflicting(a, b) is False


def test_are_conflicting_different_assets():
    a = _trade("s1", product="ETH-USD", side="buy")
    b = _trade("s2", product="BTC-USD", side="sell")
    assert _are_conflicting(a, b) is False


# ---------------------------------------------------------------------------
# Composite score
# ---------------------------------------------------------------------------

def test_composite_score_edge_only():
    cfg = AllocatorConfig(edge_weight=1.0, confidence_weight=0.0, risk_penalty_weight=0.0)
    alloc = PortfolioAllocator(cfg)
    t = _trade(edge=75.0, confidence=0.5, risk_score=0.8)
    score = alloc.composite_score(t)
    assert abs(score - 75.0) < 0.001, f"expected 75.0, got {score}"


def test_composite_score_all_weights():
    # 50 + 0.5 * (0.8 * 100) - 0.2 * (0.3 * 100) = 50 + 40 - 6 = 84
    cfg = AllocatorConfig(edge_weight=1.0, confidence_weight=0.5, risk_penalty_weight=0.2)
    alloc = PortfolioAllocator(cfg)
    t = _trade(edge=50.0, confidence=0.8, risk_score=0.3)
    score = alloc.composite_score(t)
    assert abs(score - 84.0) < 0.001, f"expected 84.0, got {score}"


# ---------------------------------------------------------------------------
# single_best mode
# ---------------------------------------------------------------------------

def test_single_best_returns_highest_scored():
    cfg = AllocatorConfig(mode="single_best", available_capital_usd=1000.0)
    alloc = PortfolioAllocator(cfg)
    low = _trade("low_edge", edge=20.0)
    high = _trade("high_edge", edge=80.0)
    result = alloc.select([low, high])
    assert len(result) == 1, f"expected 1 trade, got {len(result)}"
    assert result[0].strategy_name == "high_edge"


def test_single_best_empty_proposals():
    alloc = PortfolioAllocator(AllocatorConfig(mode="single_best"))
    assert alloc.select([]) == []


# ---------------------------------------------------------------------------
# priority_with_fallback: both trades accepted
# ---------------------------------------------------------------------------

def test_both_accepted_when_compatible():
    cfg = AllocatorConfig(
        mode="priority_with_fallback",
        available_capital_usd=500.0,
        fallback_min_score=10.0,
    )
    alloc = PortfolioAllocator(cfg)
    t1 = _trade("spot", product="ETH-USD", side="buy", edge=80.0, notional=100.0)
    t2 = _trade("momentum", product="ETH-USD", side="buy", edge=40.0, notional=100.0)
    result = alloc.select([t1, t2])
    assert len(result) == 2, f"expected 2 trades, got {len(result)}"
    assert result[0].strategy_name == "spot"
    assert result[1].strategy_name == "momentum"


# ---------------------------------------------------------------------------
# Direction conflict rejection
# ---------------------------------------------------------------------------

def test_direction_conflict_rejects_fallback():
    cfg = AllocatorConfig(
        mode="priority_with_fallback",
        available_capital_usd=500.0,
        fallback_min_score=0.0,
    )
    alloc = PortfolioAllocator(cfg)
    buyer = _trade("buyer", product="ETH-USD", side="buy", edge=80.0, notional=100.0)
    seller = _trade("seller", product="ETH-USD", side="sell", edge=60.0, notional=100.0)
    result = alloc.select([buyer, seller])
    assert len(result) == 1, f"expected 1 trade, got {len(result)}"
    assert result[0].strategy_name == "buyer"


# ---------------------------------------------------------------------------
# Capital constraint
# ---------------------------------------------------------------------------

def test_insufficient_capital_rejects_second():
    cfg = AllocatorConfig(
        mode="priority_with_fallback",
        available_capital_usd=350.0,
        fallback_min_score=0.0,
    )
    alloc = PortfolioAllocator(cfg)
    t1 = _trade("s1", edge=80.0, notional=300.0)
    t2 = _trade("s2", edge=60.0, notional=200.0)  # 300 + 200 > 350
    result = alloc.select([t1, t2])
    assert len(result) == 1
    assert result[0].strategy_name == "s1"


def test_primary_rejected_when_exceeds_capital():
    cfg = AllocatorConfig(mode="priority_with_fallback", available_capital_usd=50.0)
    alloc = PortfolioAllocator(cfg)
    t1 = _trade("s1", edge=80.0, notional=100.0)  # 100 > 50
    result = alloc.select([t1])
    assert result == [], f"expected no trades, got {result}"


# ---------------------------------------------------------------------------
# ETH exposure cap
# ---------------------------------------------------------------------------

def test_eth_exposure_cap_rejects_second_buy():
    cfg = AllocatorConfig(
        mode="priority_with_fallback",
        available_capital_usd=1000.0,
        max_eth_exposure_usd=150.0,
        fallback_min_score=0.0,
    )
    alloc = PortfolioAllocator(cfg)
    t1 = _trade("s1", product="ETH-USD", side="buy", edge=80.0, notional=100.0)
    t2 = _trade("s2", product="ETH-USD", side="buy", edge=60.0, notional=100.0)  # 200 > 150
    result = alloc.select([t1, t2])
    assert len(result) == 1
    assert result[0].strategy_name == "s1"


def test_eth_exposure_cap_disabled_when_zero():
    cfg = AllocatorConfig(
        mode="priority_with_fallback",
        available_capital_usd=1000.0,
        max_eth_exposure_usd=0.0,  # disabled
        fallback_min_score=0.0,
    )
    alloc = PortfolioAllocator(cfg)
    t1 = _trade("s1", product="ETH-USD", side="buy", edge=80.0, notional=300.0)
    t2 = _trade("s2", product="ETH-USD", side="buy", edge=60.0, notional=300.0)
    result = alloc.select([t1, t2])
    assert len(result) == 2


def test_eth_cap_does_not_block_sell():
    cfg = AllocatorConfig(
        mode="priority_with_fallback",
        available_capital_usd=1000.0,
        max_eth_exposure_usd=50.0,
        fallback_min_score=0.0,
    )
    alloc = PortfolioAllocator(cfg)
    t1 = _trade("s1", product="ETH-USD", side="sell", edge=80.0, notional=300.0)
    t2 = _trade("s2", product="BTC-USD", side="buy", edge=60.0, notional=100.0)
    result = alloc.select([t1, t2])
    assert len(result) == 2, f"expected 2 trades, got {len(result)}"


# ---------------------------------------------------------------------------
# Fallback min-score threshold
# ---------------------------------------------------------------------------

def test_fallback_below_min_score_rejected():
    cfg = AllocatorConfig(
        mode="priority_with_fallback",
        available_capital_usd=1000.0,
        fallback_min_score=50.0,
    )
    alloc = PortfolioAllocator(cfg)
    t1 = _trade("s1", edge=80.0, notional=100.0)
    t2 = _trade("s2", edge=30.0, notional=100.0)  # score 30 < threshold 50
    result = alloc.select([t1, t2])
    assert len(result) == 1
    assert result[0].strategy_name == "s1"


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------

def test_cooldown_blocks_recently_executed():
    cfg = AllocatorConfig(mode="single_best", available_capital_usd=1000.0, cooldown_seconds=60)
    alloc = PortfolioAllocator(cfg)
    t = _trade("spot", edge=80.0)
    result = alloc.select([t])
    assert len(result) == 1
    alloc.record_executed("spot")
    result2 = alloc.select([t])
    assert result2 == [], f"expected cooldown to block, got {result2}"


def test_cooldown_zero_disables_blocking():
    cfg = AllocatorConfig(mode="single_best", available_capital_usd=1000.0, cooldown_seconds=0)
    alloc = PortfolioAllocator(cfg)
    t = _trade("spot", edge=80.0)
    alloc.record_executed("spot")
    result = alloc.select([t])
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Runner integration smoke test
# ---------------------------------------------------------------------------

def test_runner_uses_allocator_and_returns_list():
    from theta.orchestration.runner import StrategyRunner

    t1 = _trade("mock_strat", edge=80.0)

    strat = MagicMock()
    strat.name = "mock_strat"
    strat.evaluate_opportunity.return_value = t1
    strat.execute.return_value = ExecutionResult(
        success=True, strategy_name="mock_strat",
        order_id="o1", client_order_id="c1", notional_usd=100.0, dry_run=True,
    )

    runner = StrategyRunner(strategies=[strat])
    results = runner.run_once(dry_run=True)
    assert isinstance(results, list), f"run_once must return list, got {type(results)}"
    assert len(results) == 1
    assert results[0].strategy_name == "mock_strat"


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

_ALL_TESTS = [
    test_asset_from_product,
    test_are_conflicting_opposite_sides,
    test_are_conflicting_same_side,
    test_are_conflicting_different_assets,
    test_composite_score_edge_only,
    test_composite_score_all_weights,
    test_single_best_returns_highest_scored,
    test_single_best_empty_proposals,
    test_both_accepted_when_compatible,
    test_direction_conflict_rejects_fallback,
    test_insufficient_capital_rejects_second,
    test_primary_rejected_when_exceeds_capital,
    test_eth_exposure_cap_rejects_second_buy,
    test_eth_exposure_cap_disabled_when_zero,
    test_eth_cap_does_not_block_sell,
    test_fallback_below_min_score_rejected,
    test_cooldown_blocks_recently_executed,
    test_cooldown_zero_disables_blocking,
    test_runner_uses_allocator_and_returns_list,
]


def run_all() -> int:
    failures = 0
    for fn in _ALL_TESTS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            print(f"FAIL {fn.__name__}: {exc}")
            failures += 1
        except Exception as exc:
            print(f"ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
            failures += 1
    print(f"\n{len(_ALL_TESTS) - failures}/{len(_ALL_TESTS)} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all())
