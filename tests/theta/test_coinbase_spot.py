"""Unit tests for CoinbaseSpotEdgeStrategy — buy/sell decision logic and telemetry.

Tests use unittest.mock to isolate I/O (balance fetches, mid-price, API calls).
No real Coinbase credentials or network access is required.

Run directly:
    python -m tests.theta.test_coinbase_spot

Or with pytest:
    pytest tests/theta/test_coinbase_spot.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from theta.config.basis import BasisConfig
from theta.strategies.base import PlannedTrade
from theta.strategies.coinbase_spot import CoinbaseSpotEdgeStrategy

NOW = datetime.now(timezone.utc)

_MID = 3000.0  # mock ETH-USD mid price


def _cfg(log_dir: str = "/tmp/test_theta_trades", **kwargs) -> BasisConfig:
    """Return a test BasisConfig with a hurdle of 150 bps."""
    base = dict(
        cb_taker_fee_bps=60.0,
        slippage_buffer_bps=5.0,
        min_edge_bps=20.0,
        min_notional_usd=1.0,
        max_notional_usd=500.0,
        log_dir=log_dir,
    )
    base.update(kwargs)
    return BasisConfig(**base)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# 1. Positive edge + sufficient USD balance → BUY
# ---------------------------------------------------------------------------

def test_positive_edge_with_usd_balance_produces_buy():
    strat = CoinbaseSpotEdgeStrategy(config=_cfg(), signal_edge_bps=200.0)

    with patch("theta.marketdata.coinbase.get_quote_balance", return_value=50.0), \
         patch("theta.marketdata.coinbase.get_spot_mid_price", return_value=_MID):
        planned = strat.evaluate_opportunity(NOW)

    _assert(planned is not None, "expected PlannedTrade, got None")
    _assert(planned.side == "buy", f"expected side=buy, got {planned.side}")
    _assert(planned.notional_usd == 50.0, f"expected notional=50, got {planned.notional_usd}")
    _assert(planned.expected_edge_bps == 200.0, f"expected edge=200, got {planned.expected_edge_bps}")
    _assert(planned.exchange == "coinbase", f"unexpected exchange {planned.exchange}")
    print("PASS test_positive_edge_with_usd_balance_produces_buy")


# ---------------------------------------------------------------------------
# 2. Negative edge + sufficient ETH balance → SELL
# ---------------------------------------------------------------------------

def test_negative_edge_with_eth_balance_produces_sell():
    # signal_edge_bps = -200 → sell signal (magnitude 200 > hurdle 150)
    strat = CoinbaseSpotEdgeStrategy(config=_cfg(), signal_edge_bps=-200.0)

    with patch("theta.marketdata.coinbase.get_quote_balance", return_value=0.0), \
         patch("theta.marketdata.coinbase.get_base_balance", return_value=0.01), \
         patch("theta.marketdata.coinbase.get_spot_mid_price", return_value=_MID):
        planned = strat.evaluate_opportunity(NOW)

    # 0.01 ETH × $3000/ETH = $30 USD notional
    _assert(planned is not None, "expected PlannedTrade for sell signal, got None")
    _assert(planned.side == "sell", f"expected side=sell, got {planned.side}")
    _assert(
        abs(planned.notional_usd - 30.0) < 0.01,
        f"expected notional≈30, got {planned.notional_usd}",
    )
    _assert(planned.expected_edge_bps == 200.0, f"expected abs_edge=200, got {planned.expected_edge_bps}")
    print("PASS test_negative_edge_with_eth_balance_produces_sell")


# ---------------------------------------------------------------------------
# 3. Zero quote AND zero base balance → NO TRADE
# ---------------------------------------------------------------------------

def test_zero_balances_return_no_trade():
    strat = CoinbaseSpotEdgeStrategy(config=_cfg(), signal_edge_bps=200.0)

    with patch("theta.marketdata.coinbase.get_quote_balance", return_value=0.0), \
         patch("theta.marketdata.coinbase.get_base_balance", return_value=0.0), \
         patch("theta.marketdata.coinbase.get_spot_mid_price", return_value=_MID):
        planned = strat.evaluate_opportunity(NOW)

    _assert(planned is None, "expected None for zero quote balance + positive edge")
    print("PASS test_zero_balances_return_no_trade")


def test_zero_eth_balance_no_sell():
    strat = CoinbaseSpotEdgeStrategy(config=_cfg(), signal_edge_bps=-200.0)

    with patch("theta.marketdata.coinbase.get_quote_balance", return_value=0.0), \
         patch("theta.marketdata.coinbase.get_base_balance", return_value=0.0), \
         patch("theta.marketdata.coinbase.get_spot_mid_price", return_value=_MID):
        planned = strat.evaluate_opportunity(NOW)

    _assert(planned is None, "expected None for zero ETH balance + sell signal")
    print("PASS test_zero_eth_balance_no_sell")


# ---------------------------------------------------------------------------
# 4. Edge in no-trade band → NO TRADE
# ---------------------------------------------------------------------------

def test_edge_below_hurdle_no_trade():
    # hurdle = 150 bps; 100 bps is within the no-trade band
    strat = CoinbaseSpotEdgeStrategy(config=_cfg(), signal_edge_bps=100.0)

    with patch("theta.marketdata.coinbase.get_quote_balance", return_value=100.0), \
         patch("theta.marketdata.coinbase.get_spot_mid_price", return_value=_MID):
        planned = strat.evaluate_opportunity(NOW)

    _assert(planned is None, "expected None for edge 100 < hurdle 150")
    print("PASS test_edge_below_hurdle_no_trade")


def test_negative_edge_above_neg_hurdle_no_trade():
    # -100 bps is within the no-trade band (|−100| < 150)
    strat = CoinbaseSpotEdgeStrategy(config=_cfg(), signal_edge_bps=-100.0)

    with patch("theta.marketdata.coinbase.get_quote_balance", return_value=0.0), \
         patch("theta.marketdata.coinbase.get_base_balance", return_value=0.01), \
         patch("theta.marketdata.coinbase.get_spot_mid_price", return_value=_MID):
        planned = strat.evaluate_opportunity(NOW)

    _assert(planned is None, "expected None for edge -100 within ±150 no-trade band")
    print("PASS test_negative_edge_above_neg_hurdle_no_trade")


# ---------------------------------------------------------------------------
# 5. dry_run=True → no create_order call, trade logged with status="dry_run"
# ---------------------------------------------------------------------------

def test_dry_run_does_not_call_create_order():
    tmp = tempfile.mkdtemp()
    strat = CoinbaseSpotEdgeStrategy(config=_cfg(log_dir=tmp), signal_edge_bps=200.0)

    mock_cb = MagicMock()
    planned = PlannedTrade(
        strategy_name=strat.name,
        exchange="coinbase",
        product_id="ETH-USD",
        side="buy",
        notional_usd=50.0,
        expected_edge_bps=200.0,
    )

    with patch("theta.execution.coinbase._require_client", return_value=mock_cb), \
         patch("theta.marketdata.coinbase.get_spot_mid_price", return_value=_MID):
        result = strat.execute(planned, dry_run=True)

    _assert(result.success, f"expected success in dry_run, got error={result.error}")
    _assert(result.dry_run is True, "expected dry_run=True in result")
    mock_cb.create_order.assert_not_called()

    # Verify status in the trade log
    trades_path = os.path.join(tmp, "trades.jsonl")
    _assert(os.path.exists(trades_path), "trades.jsonl not created in dry_run")
    with open(trades_path) as fh:
        records = [json.loads(l) for l in fh if l.strip()]
    _assert(len(records) == 1, f"expected 1 record, got {len(records)}")
    _assert(records[0]["status"] == "dry_run", f"expected status=dry_run, got {records[0]['status']}")
    print("PASS test_dry_run_does_not_call_create_order")


# ---------------------------------------------------------------------------
# 6. Live buy → create_order called, trade logged with status="live"
# ---------------------------------------------------------------------------

def test_live_buy_logged_with_live_status():
    tmp = tempfile.mkdtemp()
    strat = CoinbaseSpotEdgeStrategy(config=_cfg(log_dir=tmp), signal_edge_bps=200.0)

    mock_cb = MagicMock()
    mock_resp = MagicMock()
    mock_resp.success = True
    mock_resp.order_id = "live-order-123"
    mock_resp.success_response = MagicMock(order_id="live-order-123")
    mock_cb.create_order.return_value = mock_resp

    planned = PlannedTrade(
        strategy_name=strat.name,
        exchange="coinbase",
        product_id="ETH-USD",
        side="buy",
        notional_usd=50.0,
        expected_edge_bps=200.0,
    )

    with patch("theta.execution.coinbase._require_client", return_value=mock_cb), \
         patch("theta.marketdata.coinbase.get_spot_mid_price", return_value=_MID):
        result = strat.execute(planned, dry_run=False)

    _assert(result.success, f"expected success, got error={result.error}")
    _assert(result.dry_run is False, "expected dry_run=False in result")
    mock_cb.create_order.assert_called_once()

    trades_path = os.path.join(tmp, "trades.jsonl")
    with open(trades_path) as fh:
        records = [json.loads(l) for l in fh if l.strip()]
    _assert(len(records) == 1, f"expected 1 record, got {len(records)}")
    _assert(records[0]["status"] == "live", f"expected status=live, got {records[0]['status']}")
    _assert(records[0]["side"] == "buy", f"expected side=buy, got {records[0]['side']}")
    print("PASS test_live_buy_logged_with_live_status")


# ---------------------------------------------------------------------------
# 7. Live sell → create_order called, trade logged with status="live", side="sell"
# ---------------------------------------------------------------------------

def test_live_sell_logged_with_live_status():
    tmp = tempfile.mkdtemp()
    strat = CoinbaseSpotEdgeStrategy(config=_cfg(log_dir=tmp), signal_edge_bps=-200.0)

    mock_cb = MagicMock()
    mock_resp = MagicMock()
    mock_resp.success = True
    mock_resp.order_id = "live-sell-456"
    mock_resp.success_response = MagicMock(order_id="live-sell-456")
    mock_cb.create_order.return_value = mock_resp

    planned = PlannedTrade(
        strategy_name=strat.name,
        exchange="coinbase",
        product_id="ETH-USD",
        side="sell",
        notional_usd=30.0,
        expected_edge_bps=200.0,
    )

    with patch("theta.execution.coinbase._require_client", return_value=mock_cb), \
         patch("theta.marketdata.coinbase.get_spot_mid_price", return_value=_MID):
        result = strat.execute(planned, dry_run=False)

    _assert(result.success, f"expected success, got error={result.error}")
    mock_cb.create_order.assert_called_once()

    trades_path = os.path.join(tmp, "trades.jsonl")
    with open(trades_path) as fh:
        records = [json.loads(l) for l in fh if l.strip()]
    _assert(records[0]["status"] == "live", f"expected status=live, got {records[0]['status']}")
    _assert(records[0]["side"] == "sell", f"expected side=sell, got {records[0]['side']}")
    print("PASS test_live_sell_logged_with_live_status")


# ---------------------------------------------------------------------------
# 8. Coinbase API error → logged as "failed", ExecutionResult.success=False
# ---------------------------------------------------------------------------

def test_api_error_logged_as_failed():
    tmp = tempfile.mkdtemp()
    strat = CoinbaseSpotEdgeStrategy(config=_cfg(log_dir=tmp))

    mock_cb = MagicMock()
    mock_cb.create_order.side_effect = RuntimeError("network timeout")

    planned = PlannedTrade(
        strategy_name=strat.name,
        exchange="coinbase",
        product_id="ETH-USD",
        side="buy",
        notional_usd=50.0,
        expected_edge_bps=200.0,
    )

    with patch("theta.execution.coinbase._require_client", return_value=mock_cb), \
         patch("theta.marketdata.coinbase.get_spot_mid_price", return_value=_MID):
        result = strat.execute(planned, dry_run=False)

    _assert(result.success is False, "expected failure on API error")
    _assert("network timeout" in (result.error or ""), f"expected error to contain 'network timeout', got: {result.error}")

    trades_path = os.path.join(tmp, "trades.jsonl")
    with open(trades_path) as fh:
        records = [json.loads(l) for l in fh if l.strip()]
    _assert(len(records) == 1, f"expected 1 error record, got {len(records)}")
    _assert(records[0]["status"] == "failed", f"expected status=failed, got {records[0]['status']}")
    print("PASS test_api_error_logged_as_failed")


# ---------------------------------------------------------------------------
# 9. ETH position too small (dust) → no sell trade
# ---------------------------------------------------------------------------

def test_dust_eth_position_no_sell():
    # 0.0001 ETH × $3000 = $0.30 USD < min_notional_usd=1.0
    strat = CoinbaseSpotEdgeStrategy(config=_cfg(min_notional_usd=1.0), signal_edge_bps=-200.0)

    with patch("theta.marketdata.coinbase.get_quote_balance", return_value=0.0), \
         patch("theta.marketdata.coinbase.get_base_balance", return_value=0.0001), \
         patch("theta.marketdata.coinbase.get_spot_mid_price", return_value=_MID):
        planned = strat.evaluate_opportunity(NOW)

    _assert(planned is None, "expected None for dust ETH position below min_notional")
    print("PASS test_dust_eth_position_no_sell")


# ---------------------------------------------------------------------------
# 10. Live buy → write_trade() called with strategy_name (DB write path)
# ---------------------------------------------------------------------------

def test_live_buy_calls_write_trade_with_strategy_name():
    """write_trade() must be invoked with strategy_name so theta_trades gets a row."""
    tmp = tempfile.mkdtemp()
    strat = CoinbaseSpotEdgeStrategy(config=_cfg(log_dir=tmp), signal_edge_bps=200.0)

    mock_cb = MagicMock()
    mock_resp = MagicMock()
    mock_resp.success = True
    mock_resp.order_id = "db-write-order-001"
    mock_resp.success_response = MagicMock(order_id="db-write-order-001")
    mock_cb.create_order.return_value = mock_resp

    planned = PlannedTrade(
        strategy_name=strat.name,
        exchange="coinbase",
        product_id="ETH-USD",
        side="buy",
        notional_usd=50.0,
        expected_edge_bps=200.0,
    )

    with patch("theta.execution.coinbase._require_client", return_value=mock_cb), \
         patch("theta.marketdata.coinbase.get_spot_mid_price", return_value=_MID), \
         patch("theta.db.writer.write_trade") as mock_write_trade:
        result = strat.execute(planned, dry_run=False)

    _assert(result.success, f"expected success, got error={result.error}")
    mock_write_trade.assert_called_once()
    call_kwargs = mock_write_trade.call_args
    written_strategy = call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("strategy_name")
    _assert(
        written_strategy == strat.name,
        f"expected strategy_name={strat.name!r}, write_trade got {written_strategy!r}",
    )
    print("PASS test_live_buy_calls_write_trade_with_strategy_name")


# ---------------------------------------------------------------------------
# 11. dry_run=True → write_trade() called with strategy_name (dry-run DB path)
# ---------------------------------------------------------------------------

def test_dry_run_calls_write_trade_with_strategy_name():
    """DB write must also fire for dry-run trades so the dashboard can show them."""
    tmp = tempfile.mkdtemp()
    strat = CoinbaseSpotEdgeStrategy(config=_cfg(log_dir=tmp), signal_edge_bps=200.0)

    mock_cb = MagicMock()

    planned = PlannedTrade(
        strategy_name=strat.name,
        exchange="coinbase",
        product_id="ETH-USD",
        side="buy",
        notional_usd=50.0,
        expected_edge_bps=200.0,
    )

    with patch("theta.execution.coinbase._require_client", return_value=mock_cb), \
         patch("theta.marketdata.coinbase.get_spot_mid_price", return_value=_MID), \
         patch("theta.db.writer.write_trade") as mock_write_trade:
        result = strat.execute(planned, dry_run=True)

    _assert(result.success, f"expected success in dry_run, got error={result.error}")
    mock_write_trade.assert_called_once()
    call_kwargs = mock_write_trade.call_args
    written_strategy = call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("strategy_name")
    _assert(
        written_strategy == strat.name,
        f"expected strategy_name={strat.name!r}, write_trade got {written_strategy!r}",
    )
    print("PASS test_dry_run_calls_write_trade_with_strategy_name")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_ALL_TESTS = [
    test_positive_edge_with_usd_balance_produces_buy,
    test_negative_edge_with_eth_balance_produces_sell,
    test_zero_balances_return_no_trade,
    test_zero_eth_balance_no_sell,
    test_edge_below_hurdle_no_trade,
    test_negative_edge_above_neg_hurdle_no_trade,
    test_dry_run_does_not_call_create_order,
    test_live_buy_logged_with_live_status,
    test_live_sell_logged_with_live_status,
    test_api_error_logged_as_failed,
    test_dust_eth_position_no_sell,
    test_live_buy_calls_write_trade_with_strategy_name,
    test_dry_run_calls_write_trade_with_strategy_name,
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
