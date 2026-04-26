"""Tests for execute() — dry-run flow, risk blocking, unhedged leg scenario."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.polymarket.config import PolymarketConfig
from src.polymarket.executor import ExecutionResult, _check_pol_gas, _place_order, execute
from src.polymarket.opportunities import Opportunity
from src.polymarket.positions import PositionsLedger, new_position
from src.polymarket.risk import RiskGuard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides: Any) -> PolymarketConfig:
    defaults: dict[str, Any] = {
        "api_key": "k",
        "api_secret": "s",
        "passphrase": "p",
        "private_key": "pk",
        "scan_interval_sec": 30,
        "min_edge_pct": 1.5,
        "clob_base_url": "https://clob.polymarket.com",
        "kalshi_base_url": "https://trading-api.kalshi.com/trade-api/v2",
        "max_retries": 3,
        "timeout_seconds": 15.0,
        "max_trade_usdc": 200.0,
        "max_positions": 5,
        "daily_loss_limit": 200.0,
        "dry_run": True,
        "min_volume_24h": 10_000.0,
        "positions_path": "data/polymarket_positions.json",
    }
    defaults.update(overrides)
    if defaults.get("dry_run") is False:
        defaults.setdefault("trading_mode", "live")
        defaults.setdefault("trading_venue", "polymarket")
        defaults.setdefault("live_trading_enabled", True)
        defaults.setdefault("signal_provider", "synthetic")
        defaults.setdefault("poly_trading_mode", "live")
        defaults.setdefault("alpaca_trading_mode", "disabled")
    return PolymarketConfig(**defaults)  # type: ignore[arg-type]


def _make_opp(**overrides: Any) -> Opportunity:
    defaults: dict[str, Any] = {
        "strategy": "orderbook_spread",
        "market_question": "Will BTC hit $100k?",
        "edge_pct": 5.0,
        "action": "buy YES @ 0.40 + buy NO @ 0.40",
        "confidence": "high",
        "notes": "yes_ask=0.40 no_ask=0.40 total_cost=0.80 net_payout=0.98 fee_pct=0.02",
        "condition_id": "0xabc",
        "yes_token_id": "t-yes",
        "no_token_id": "t-no",
        "entry_price_yes": 0.40,
        "entry_price_no": 0.40,
        "volume_24h": 50_000.0,
    }
    defaults.update(overrides)
    return Opportunity(**defaults)


def _ledger(tmp_path: Path) -> PositionsLedger:
    return PositionsLedger(path=tmp_path / "positions.json")


def _guard(tmp_path: Path, config: PolymarketConfig | None = None) -> RiskGuard:
    cfg = config or _make_config()
    return RiskGuard(config=cfg, ledger=_ledger(tmp_path))


# ---------------------------------------------------------------------------
# Dry-run end-to-end
# ---------------------------------------------------------------------------

def test_execute_dry_run_returns_success_without_api_call(tmp_path: Path) -> None:
    config = _make_config(dry_run=True)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)
    opp = _make_opp()

    result = execute(opp, config=config, risk_guard=guard, ledger=ledger)

    assert result.success is True
    assert result.error == "dry_run"
    assert result.size_usdc == pytest.approx(config.max_trade_usdc)


def test_execute_dry_run_does_not_write_positions(tmp_path: Path) -> None:
    config = _make_config(dry_run=True)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)

    execute(_make_opp(), config=config, risk_guard=guard, ledger=ledger)

    assert ledger.open_count() == 0


def test_execute_dry_run_runs_risk_checks(tmp_path: Path) -> None:
    config = _make_config(dry_run=True)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)
    guard.pause()  # block execution via pause

    result = execute(_make_opp(), config=config, risk_guard=guard, ledger=ledger)

    assert result.success is False
    assert "risk_check_failed" in result.error


# ---------------------------------------------------------------------------
# Risk blocking
# ---------------------------------------------------------------------------

def test_execute_blocked_by_low_edge(tmp_path: Path) -> None:
    config = _make_config(dry_run=True, min_edge_pct=10.0)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)
    opp = _make_opp(edge_pct=5.0)  # below required 10%

    result = execute(opp, config=config, risk_guard=guard, ledger=ledger)

    assert result.success is False
    assert "risk_check_failed" in result.error


def test_execute_blocked_by_low_confidence(tmp_path: Path) -> None:
    config = _make_config(dry_run=True)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)
    opp = _make_opp(confidence="low")

    result = execute(opp, config=config, risk_guard=guard, ledger=ledger)

    assert result.success is False
    assert "risk_check_failed" in result.error


def test_execute_blocked_by_insufficient_volume(tmp_path: Path) -> None:
    config = _make_config(dry_run=True, min_volume_24h=100_000.0)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)
    opp = _make_opp(volume_24h=5_000.0)

    result = execute(opp, config=config, risk_guard=guard, ledger=ledger)

    assert result.success is False


# ---------------------------------------------------------------------------
# Strategy scope
# ---------------------------------------------------------------------------

def test_execute_skips_cross_market_strategy(tmp_path: Path) -> None:
    config = _make_config(dry_run=True)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)
    opp = _make_opp(strategy="cross_market")

    result = execute(opp, config=config, risk_guard=guard, ledger=ledger)

    assert result.success is False
    assert "not_executable_in_phase2" in result.error or "cross_market" in result.error


def test_execute_correlated_strategy_dry_run_succeeds(tmp_path: Path) -> None:
    # correlated_markets is executable; dry_run=True returns success=True with error="dry_run"
    config = _make_config(dry_run=True)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)
    opp = _make_opp(strategy="correlated_markets")

    result = execute(opp, config=config, risk_guard=guard, ledger=ledger)

    assert result.success is True
    assert result.error == "dry_run"


# ---------------------------------------------------------------------------
# Live execution — orderbook spread (mocked _place_order)
# ---------------------------------------------------------------------------

def _mock_order_response(order_id: str, price: float) -> dict:
    return {"orderID": order_id, "price": price, "status": "matched"}


def test_execute_live_both_legs_records_open_position(tmp_path: Path) -> None:
    config = _make_config(dry_run=False)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)

    yes_resp = _mock_order_response("ord-yes-1", 0.40)
    no_resp = _mock_order_response("ord-no-1", 0.40)

    with patch("src.polymarket.executor._place_order", side_effect=[yes_resp, no_resp]):
        result = execute(_make_opp(), config=config, risk_guard=guard, ledger=ledger)

    assert result.success is True
    assert "ord-yes-1" in result.order_id
    assert "ord-no-1" in result.order_id
    assert ledger.open_count() == 1

    pos = ledger.load()[0]
    assert pos.side == "YES+NO"
    assert pos.status == "open"
    assert pos.strategy == "orderbook_spread"


def test_execute_live_records_correct_fill_price(tmp_path: Path) -> None:
    config = _make_config(dry_run=False)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)

    with patch(
        "src.polymarket.executor._place_order",
        side_effect=[
            _mock_order_response("yes-ord", 0.39),
            _mock_order_response("no-ord", 0.41),
        ],
    ):
        result = execute(_make_opp(), config=config, risk_guard=guard, ledger=ledger)

    assert result.fill_price == pytest.approx(0.40, abs=0.01)


# ---------------------------------------------------------------------------
# Unhedged leg scenario
# ---------------------------------------------------------------------------

def test_execute_live_records_unhedged_when_no_leg_fails(tmp_path: Path) -> None:
    config = _make_config(dry_run=False)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)

    yes_resp = _mock_order_response("yes-ord", 0.40)

    with patch(
        "src.polymarket.executor._place_order",
        side_effect=[yes_resp, RuntimeError("NO leg network timeout")],
    ):
        result = execute(_make_opp(), config=config, risk_guard=guard, ledger=ledger)

    assert result.success is False
    assert "no_leg_failed_unhedged" in result.error
    assert result.order_id == "yes-ord"

    positions = ledger.load()
    assert len(positions) == 1
    assert positions[0].status == "unhedged"
    assert positions[0].side == "YES"


def test_execute_live_unhedged_position_has_correct_size(tmp_path: Path) -> None:
    config = _make_config(dry_run=False, max_trade_usdc=200.0)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)
    opp = _make_opp(entry_price_yes=0.40, entry_price_no=0.40)

    yes_resp = _mock_order_response("yes-ord", 0.40)

    with patch(
        "src.polymarket.executor._place_order",
        side_effect=[yes_resp, RuntimeError("timeout")],
    ):
        execute(opp, config=config, risk_guard=guard, ledger=ledger)

    pos = ledger.load()[0]
    # YES leg should be ~half the total (100 out of 200 USDC when both asks are equal)
    assert pos.size_usdc == pytest.approx(100.0, abs=1.0)


def test_execute_live_no_leg_first_fails_no_unhedged_recorded(tmp_path: Path) -> None:
    """If the YES leg itself fails, no position is recorded (nothing filled)."""
    config = _make_config(dry_run=False)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)

    with patch(
        "src.polymarket.executor._place_order",
        side_effect=[RuntimeError("YES leg rejected")],
    ):
        result = execute(_make_opp(), config=config, risk_guard=guard, ledger=ledger)

    assert result.success is False
    assert "yes_leg_failed" in result.error
    assert ledger.open_count() == 0  # nothing recorded


# ---------------------------------------------------------------------------
# _place_order import guard
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _check_pol_gas
# ---------------------------------------------------------------------------

def test_check_pol_gas_returns_true_when_web3_missing() -> None:
    import builtins
    real_import = builtins.__import__

    def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in ("web3", "eth_account"):
            raise ImportError(f"no module named {name}")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        assert _check_pol_gas("any_key") is True


def test_check_pol_gas_returns_true_when_key_invalid() -> None:
    with patch("src.polymarket.executor._check_pol_gas", wraps=_check_pol_gas):
        result = _check_pol_gas("not-a-real-key")
    # "not-a-real-key" is not a valid private key — eth_account raises, we fail open
    assert result is True


def test_check_pol_gas_returns_true_on_rpc_error() -> None:
    mock_account = MagicMock()
    mock_account.address = "0xDeadBeef00000000000000000000000000000000"
    mock_w3 = MagicMock()
    mock_w3.eth.get_balance.side_effect = Exception("RPC connection refused")
    mock_web3_cls = MagicMock(return_value=mock_w3)

    with patch.dict("sys.modules", {"web3": MagicMock(Web3=mock_web3_cls), "eth_account": MagicMock(Account=MagicMock(from_key=MagicMock(return_value=mock_account)))}):
        result = _check_pol_gas("0x" + "a" * 64)
    assert result is True


def test_check_pol_gas_returns_false_when_balance_too_low() -> None:
    mock_account = MagicMock()
    mock_account.address = "0xDeadBeef00000000000000000000000000000000"
    mock_w3 = MagicMock()
    mock_w3.eth.get_balance.return_value = int(0.001 * 1e18)  # 0.001 POL — below 0.005 threshold

    with patch.dict("sys.modules", {
        "web3": MagicMock(Web3=MagicMock(return_value=mock_w3, HTTPProvider=MagicMock())),
        "eth_account": MagicMock(Account=MagicMock(from_key=MagicMock(return_value=mock_account))),
    }):
        result = _check_pol_gas("0x" + "a" * 64)
    assert result is False


def test_check_pol_gas_returns_true_when_balance_sufficient() -> None:
    mock_account = MagicMock()
    mock_account.address = "0xDeadBeef00000000000000000000000000000000"
    mock_w3 = MagicMock()
    mock_w3.eth.get_balance.return_value = int(0.1 * 1e18)  # 0.1 POL — well above threshold

    with patch.dict("sys.modules", {
        "web3": MagicMock(Web3=MagicMock(return_value=mock_w3, HTTPProvider=MagicMock())),
        "eth_account": MagicMock(Account=MagicMock(from_key=MagicMock(return_value=mock_account))),
    }):
        result = _check_pol_gas("0x" + "a" * 64)
    assert result is True


def test_execute_live_aborts_when_pol_gas_insufficient(tmp_path: Path) -> None:
    config = _make_config(dry_run=False)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)

    with patch("src.polymarket.executor._check_pol_gas", return_value=False):
        result = execute(_make_opp(), config=config, risk_guard=guard, ledger=ledger)

    assert result.success is False
    assert result.error == "pol_gas_insufficient"
    assert ledger.open_count() == 0


def test_execute_live_proceeds_when_pol_gas_ok(tmp_path: Path) -> None:
    config = _make_config(dry_run=False)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)

    yes_resp = _mock_order_response("ord-yes-gas", 0.40)
    no_resp = _mock_order_response("ord-no-gas", 0.40)

    with (
        patch("src.polymarket.executor._check_pol_gas", return_value=True),
        patch("src.polymarket.executor._place_order", side_effect=[yes_resp, no_resp]),
    ):
        result = execute(_make_opp(), config=config, risk_guard=guard, ledger=ledger)

    assert result.success is True
    assert ledger.open_count() == 1


def test_execute_dry_run_skips_pol_gas_check(tmp_path: Path) -> None:
    config = _make_config(dry_run=True)
    ledger = _ledger(tmp_path)
    guard = RiskGuard(config=config, ledger=ledger)

    with patch("src.polymarket.executor._check_pol_gas") as mock_gas:
        result = execute(_make_opp(), config=config, risk_guard=guard, ledger=ledger)

    mock_gas.assert_not_called()
    assert result.success is True


# ---------------------------------------------------------------------------
# _place_order import guard
# ---------------------------------------------------------------------------

def test_place_order_raises_runtime_error_when_py_clob_missing() -> None:
    """_place_order should raise RuntimeError with a helpful message if the
    optional py-clob-client-v2 dependency is not installed."""
    config = _make_config()
    import builtins
    real_import = builtins.__import__

    def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if "py_clob_client_v2" in name:
            raise ImportError("no module named py_clob_client_v2")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        with pytest.raises(RuntimeError, match="py-clob-client-v2"):
            _place_order(config, token_id="t", size_usdc=100.0, price=0.5, side="BUY")
