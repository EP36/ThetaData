"""Unit tests for theta.config.basis and theta.execution.coinbase.

These are plain assertions — no pytest required.  Run directly:

    python -m tests.theta.test_basis

Or with pytest (also works):

    pytest tests/theta/test_basis.py -v
"""
from __future__ import annotations

import sys
import os

# Ensure repo root is importable when run directly
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from theta.config.basis import BasisConfig
from theta.execution.coinbase import should_trade_spot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_cfg(**overrides) -> BasisConfig:
    """Return a BasisConfig with predictable test defaults; overrides win."""
    # round_trip_cost = 2 * (60 + 5)  = 130 bps
    # hurdle          = 130 + 20      = 150 bps
    base = dict(
        cb_taker_fee_bps=60.0,      # 0.60%
        slippage_buffer_bps=5.0,    # 0.05%
        min_edge_bps=20.0,          # 0.20% safety margin
        min_notional_usd=1.0,
        max_notional_usd=500.0,
    )
    base.update(overrides)
    return BasisConfig(**base)


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# BasisConfig tests
# ---------------------------------------------------------------------------

def test_config_derived_properties():
    cfg = _default_cfg()
    _assert(cfg.one_way_cost_bps == 65.0,
            f"one_way_cost expected 65.0 got {cfg.one_way_cost_bps}")
    _assert(cfg.round_trip_cost_bps == 130.0,
            f"round_trip expected 130.0 got {cfg.round_trip_cost_bps}")
    _assert(cfg.hurdle_bps == 150.0,
            f"hurdle expected 150.0 got {cfg.hurdle_bps}")
    print("PASS test_config_derived_properties")


def test_config_from_env_uses_defaults_when_vars_unset():
    # Remove any env vars that might interfere
    for key in ("CB_TAKER_FEE_BPS", "MIN_EDGE_BPS", "CB_SLIPPAGE_BUFFER_BPS"):
        os.environ.pop(key, None)

    cfg = BasisConfig.from_env()
    _assert(cfg.cb_taker_fee_bps == 60.0, "default taker fee should be 60 bps")
    _assert(cfg.min_edge_bps == 20.0,     "default min_edge_bps should be 20")
    _assert(cfg.default_quote == "USD",   "default_quote should be USD")
    print("PASS test_config_from_env_uses_defaults_when_vars_unset")


def test_config_from_env_reads_overrides():
    os.environ["CB_TAKER_FEE_BPS"] = "40"   # volume discount
    os.environ["MIN_EDGE_BPS"] = "30"
    cfg = BasisConfig.from_env()
    _assert(cfg.cb_taker_fee_bps == 40.0, f"expected 40.0 got {cfg.cb_taker_fee_bps}")
    _assert(cfg.min_edge_bps == 30.0,     f"expected 30.0 got {cfg.min_edge_bps}")
    # Clean up
    del os.environ["CB_TAKER_FEE_BPS"]
    del os.environ["MIN_EDGE_BPS"]
    print("PASS test_config_from_env_reads_overrides")


# ---------------------------------------------------------------------------
# should_trade_spot: size checks
# ---------------------------------------------------------------------------

def test_notional_too_small_is_rejected():
    cfg = _default_cfg(min_notional_usd=5.0)
    ok, reason = should_trade_spot("ETH", notional_usd=0.50, expected_edge_bps=300.0, config=cfg)
    _assert(ok is False, "expected False for notional < min")
    _assert("notional_too_small" in reason, f"unexpected reason: {reason}")
    print("PASS test_notional_too_small_is_rejected")


def test_notional_too_large_is_rejected():
    cfg = _default_cfg(max_notional_usd=100.0)
    ok, reason = should_trade_spot("ETH", notional_usd=200.0, expected_edge_bps=500.0, config=cfg)
    _assert(ok is False, "expected False for notional > max")
    _assert("notional_too_large" in reason, f"unexpected reason: {reason}")
    print("PASS test_notional_too_large_is_rejected")


# ---------------------------------------------------------------------------
# should_trade_spot: edge checks
# ---------------------------------------------------------------------------

def test_zero_edge_is_rejected():
    """No signal → no trade, always."""
    cfg = _default_cfg()   # hurdle = 150 bps
    ok, reason = should_trade_spot("ETH", notional_usd=10.0, expected_edge_bps=0.0, config=cfg)
    _assert(ok is False, "expected False for zero edge")
    _assert("edge_below_hurdle" in reason, f"unexpected reason: {reason}")
    print("PASS test_zero_edge_is_rejected")


def test_edge_below_hurdle_is_rejected():
    """Edge that covers costs but is below the safety margin."""
    cfg = _default_cfg()   # hurdle = 150 bps; round-trip cost = 130 bps
    # 140 bps: covers costs (130) but doesn't clear the 20-bps margin
    ok, reason = should_trade_spot("ETH", notional_usd=10.0, expected_edge_bps=140.0, config=cfg)
    _assert(ok is False, "expected False for edge=140 < hurdle=150")
    _assert("edge_below_hurdle" in reason, f"unexpected reason: {reason}")
    print("PASS test_edge_below_hurdle_is_rejected")


def test_edge_exactly_at_hurdle_is_approved():
    """Edge exactly meeting the hurdle clears the gate (>= semantics)."""
    cfg = _default_cfg()   # hurdle = 150 bps
    ok, reason = should_trade_spot("ETH", notional_usd=10.0, expected_edge_bps=150.0, config=cfg)
    _assert(ok is True, f"expected True for edge=150 == hurdle=150, got: {reason}")
    _assert("edge_sufficient" in reason, f"unexpected reason: {reason}")
    print("PASS test_edge_exactly_at_hurdle_is_approved")


def test_edge_well_above_hurdle_is_approved():
    """Strong edge signal → trade approved; reason includes net alpha."""
    cfg = _default_cfg()   # hurdle = 150 bps; round-trip = 130 bps
    ok, reason = should_trade_spot("ETH", notional_usd=50.0, expected_edge_bps=300.0, config=cfg)
    _assert(ok is True, f"expected True for edge=300 >> hurdle=150, got: {reason}")
    _assert("edge_sufficient" in reason, f"unexpected reason: {reason}")
    # net_after_costs = 300 - 130 = 170 bps
    _assert("170.0bps" in reason, f"expected net=170.0bps in reason: {reason}")
    print("PASS test_edge_well_above_hurdle_is_approved")


def test_no_margin_of_safety_still_requires_round_trip_cost():
    """--force equivalent: min_edge_bps=0 still requires fees + slippage."""
    cfg = _default_cfg(min_edge_bps=0.0)  # hurdle = 130 bps (costs only)
    # 129 bps: just below round-trip cost → still rejected
    ok, reason = should_trade_spot("ETH", notional_usd=10.0, expected_edge_bps=129.0, config=cfg)
    _assert(ok is False, f"expected False for edge=129 < hurdle=130, got: {reason}")
    # 130 bps: exactly at round-trip cost → approved
    ok, reason = should_trade_spot("ETH", notional_usd=10.0, expected_edge_bps=130.0, config=cfg)
    _assert(ok is True, f"expected True for edge=130 == hurdle=130, got: {reason}")
    print("PASS test_no_margin_of_safety_still_requires_round_trip_cost")


def test_reason_string_contains_fee_breakdown():
    """Rejection reason must include fee details for diagnostics."""
    cfg = _default_cfg()
    ok, reason = should_trade_spot("BTC", notional_usd=10.0, expected_edge_bps=50.0, config=cfg)
    _assert(ok is False, "expected rejection")
    _assert("60.0bps" in reason, f"expected taker fee in reason: {reason}")
    _assert("5.0bps" in reason,  f"expected slippage in reason: {reason}")
    _assert("20.0bps" in reason, f"expected margin in reason: {reason}")
    print("PASS test_reason_string_contains_fee_breakdown")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_ALL_TESTS = [
    test_config_derived_properties,
    test_config_from_env_uses_defaults_when_vars_unset,
    test_config_from_env_reads_overrides,
    test_notional_too_small_is_rejected,
    test_notional_too_large_is_rejected,
    test_zero_edge_is_rejected,
    test_edge_below_hurdle_is_rejected,
    test_edge_exactly_at_hurdle_is_approved,
    test_edge_well_above_hurdle_is_approved,
    test_no_margin_of_safety_still_requires_round_trip_cost,
    test_reason_string_contains_fee_breakdown,
]


def run_all() -> int:
    failures = 0
    for fn in _ALL_TESTS:
        try:
            fn()
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
