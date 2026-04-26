"""Unit tests for RebalanceTrigger."""
import os
import time
import pytest

from src.capital.allocator import CapitalAllocator, OpportunityScore
from src.capital.venue_balance import VenueSnapshot
import src.capital.rebalance_trigger as trigger_mod
from src.capital.rebalance_trigger import evaluate, mark_rebalance_complete


def _make_score(
    source: str,
    ann_edge: float = 100.0,
    confidence: float = 0.9,
    efficiency: float = 0.9,
    lockup: float = 1.0,
) -> OpportunityScore:
    opp = OpportunityScore(
        source=source,
        strategy="test",
        label=f"{source}-test",
        annualized_edge_pct=ann_edge,
        exec_confidence=confidence,
        capital_efficiency=efficiency,
        lockup_hours=lockup,
        raw_edge_pct=ann_edge / 365,
    )
    alloc = CapitalAllocator()
    import dataclasses
    return dataclasses.replace(opp, composite_score=alloc.score(opp))


@pytest.fixture(autouse=True)
def reset_cooldown():
    trigger_mod._LAST_REBALANCE.clear()
    yield
    trigger_mod._LAST_REBALANCE.clear()


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("REBALANCE_SCORE_GAP", "0.10")
    monkeypatch.setenv("REBALANCE_MIN_USD", "10.0")
    monkeypatch.setenv("REBALANCE_COOLDOWN_SEC", "0")
    monkeypatch.setenv("REBALANCE_DRY_RUN", "true")


def _snaps(hl_free=500.0, poly_free=200.0, cb_free=300.0) -> dict:
    return {
        "hyperliquid": VenueSnapshot("hyperliquid", hl_free, 0.0, hl_free),
        "polymarket":  VenueSnapshot("polymarket",  poly_free, 0.0, poly_free),
        "coinbase":    VenueSnapshot("coinbase",    cb_free, 0.0, cb_free),
    }


def test_no_rebalance_when_gap_below_threshold():
    low  = _make_score("polymarket", ann_edge=80.0)
    high = _make_score("hyperliquid", ann_edge=100.0)
    # gap is small; should not trigger
    decisions = evaluate([low, high], _snaps())
    # only rebalances where gap >= 0.10; these scores are close
    for d in decisions:
        assert d.score_gap < 0.10 or not d.should_rebalance


def test_rebalance_triggered_when_large_gap():
    low  = _make_score("polymarket", ann_edge=10.0,  confidence=0.3, efficiency=0.3)
    high = _make_score("hyperliquid", ann_edge=490.0, confidence=0.99, efficiency=0.99)
    decisions = evaluate([low, high], _snaps())
    triggered = [d for d in decisions if d.should_rebalance]
    assert len(triggered) >= 1
    best = triggered[0]
    assert best.source_venue == "polymarket"
    assert best.dest_venue == "hyperliquid"
    assert best.score_gap >= 0.10


def test_no_rebalance_when_insufficient_free_capital():
    low  = _make_score("polymarket", ann_edge=10.0,  confidence=0.3)
    high = _make_score("hyperliquid", ann_edge=490.0, confidence=0.99)
    snaps = _snaps(poly_free=5.0)  # below REBALANCE_MIN_USD=10
    decisions = evaluate([low, high], snaps)
    triggered = [d for d in decisions if d.source_venue == "polymarket"]
    assert len(triggered) == 0


def test_cooldown_prevents_immediate_retrigger(monkeypatch):
    monkeypatch.setenv("REBALANCE_COOLDOWN_SEC", "3600")
    low  = _make_score("polymarket", ann_edge=10.0,  confidence=0.3)
    high = _make_score("hyperliquid", ann_edge=490.0, confidence=0.99)
    mark_rebalance_complete("polymarket", "hyperliquid")
    decisions = evaluate([low, high], _snaps())
    triggered = [d for d in decisions if d.source_venue == "polymarket" and d.dest_venue == "hyperliquid"]
    assert len(triggered) == 0


def test_move_amount_capped_at_80pct_of_free():
    low  = _make_score("polymarket", ann_edge=10.0,  confidence=0.3)
    high = _make_score("hyperliquid", ann_edge=490.0, confidence=0.99)
    snaps = _snaps(poly_free=1000.0)
    decisions = evaluate([low, high], snaps)
    triggered = [d for d in decisions if d.source_venue == "polymarket" and d.dest_venue == "hyperliquid"]
    assert len(triggered) >= 1
    assert triggered[0].amount_usd <= 800.0  # 80% of 1000


def test_mark_complete_sets_cooldown():
    mark_rebalance_complete("hyperliquid", "coinbase")
    assert ("hyperliquid", "coinbase") in trigger_mod._LAST_REBALANCE
    assert trigger_mod._LAST_REBALANCE[("hyperliquid", "coinbase")] <= time.time()
