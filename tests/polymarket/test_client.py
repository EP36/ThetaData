"""Tests for ClobClient auth headers and retry logic."""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.polymarket.client import ClobClient
from src.polymarket.config import PolymarketConfig


def _make_config(**overrides: Any) -> PolymarketConfig:
    defaults: dict[str, Any] = {
        "api_key": "test-key",
        "api_secret": "test-secret",
        "passphrase": "test-pass",
        "private_key": "test-pk",
        "scan_interval_sec": 30,
        "min_edge_pct": 1.5,
        "clob_base_url": "https://clob.polymarket.com",
        "kalshi_base_url": "https://trading-api.kalshi.com/trade-api/v2",
        "max_retries": 3,
        "timeout_seconds": 15.0,
    }
    defaults.update(overrides)
    return PolymarketConfig(**defaults)


def test_auth_headers_contain_required_fields() -> None:
    client = ClobClient(config=_make_config())

    headers = client._auth_headers("GET", "/markets")

    assert headers["POLY-API-KEY"] == "test-key"
    assert headers["POLY-PASSPHRASE"] == "test-pass"
    assert "POLY-SIGNATURE" in headers
    assert "POLY-TIMESTAMP" in headers
    assert headers["POLY-TIMESTAMP"].isdigit()


def test_auth_headers_signature_matches_hmac() -> None:
    secret = "my-secret"
    config = _make_config(api_secret=secret, api_key="k", passphrase="p")
    client = ClobClient(config=config)

    fixed_ts = 1_700_000_000
    method, path = "GET", "/markets"

    with patch("src.polymarket.client.time") as mock_time:
        mock_time.time.return_value = fixed_ts
        mock_time.sleep = __import__("time").sleep
        headers = client._auth_headers(method, path)

    expected_msg = str(fixed_ts) + method + path
    expected_sig = base64.b64encode(
        hmac.new(
            secret.encode("utf-8"),
            expected_msg.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    assert headers["POLY-SIGNATURE"] == expected_sig
    assert headers["POLY-TIMESTAMP"] == str(fixed_ts)


def test_auth_headers_body_included_in_signature() -> None:
    config = _make_config(api_secret="s")
    client = ClobClient(config=config)

    with patch("src.polymarket.client.time") as mock_time:
        mock_time.time.return_value = 1_000
        mock_time.sleep = __import__("time").sleep
        h_no_body = client._auth_headers("POST", "/order", "")
        h_with_body = client._auth_headers("POST", "/order", '{"token_id":"abc"}')

    assert h_no_body["POLY-SIGNATURE"] != h_with_body["POLY-SIGNATURE"]


def _mock_http_success(payload: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    return resp


def test_fetch_markets_returns_api_payload() -> None:
    config = _make_config()
    client = ClobClient(config=config)
    payload = {"data": [{"condition_id": "0x1", "question": "BTC > $100k?"}], "next_cursor": "LTE="}

    with patch("httpx.Client") as mock_cls:
        mock_http = MagicMock()
        mock_cls.return_value.__enter__.return_value = mock_http
        mock_http.get.return_value = _mock_http_success(payload)

        result = client.fetch_markets()

    assert result == payload


def test_fetch_orderbook_passes_token_id() -> None:
    config = _make_config()
    client = ClobClient(config=config)
    payload = {"bids": [{"price": "0.55", "size": "10"}], "asks": [{"price": "0.57", "size": "10"}]}

    with patch("httpx.Client") as mock_cls:
        mock_http = MagicMock()
        mock_cls.return_value.__enter__.return_value = mock_http
        mock_http.get.return_value = _mock_http_success(payload)

        result = client.fetch_orderbook("token-abc")

    call_kwargs = mock_http.get.call_args
    assert call_kwargs.kwargs["params"]["token_id"] == "token-abc"
    assert result == payload


def test_retry_on_server_error_then_success() -> None:
    config = _make_config(max_retries=2)
    client = ClobClient(config=config)
    payload = {"data": [], "next_cursor": "LTE="}
    call_count = 0

    def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.RequestError("connection reset")
        return _mock_http_success(payload)

    with patch("httpx.Client") as mock_cls, patch("src.polymarket.client.time") as mock_time:
        mock_time.time.return_value = 1_000
        mock_time.sleep = MagicMock()
        mock_http = MagicMock()
        mock_cls.return_value.__enter__.return_value = mock_http
        mock_http.get.side_effect = side_effect

        result = client.fetch_markets()

    assert call_count == 2
    assert result == payload
    mock_time.sleep.assert_called_once_with(1)


def test_raises_after_exhausting_retries() -> None:
    config = _make_config(max_retries=1)
    client = ClobClient(config=config)

    with patch("httpx.Client") as mock_cls, patch("src.polymarket.client.time") as mock_time:
        mock_time.time.return_value = 1_000
        mock_time.sleep = MagicMock()
        mock_http = MagicMock()
        mock_cls.return_value.__enter__.return_value = mock_http
        mock_http.get.side_effect = httpx.RequestError("always fails")

        with pytest.raises(RuntimeError, match="failed after"):
            client.fetch_markets()


def test_4xx_error_not_retried() -> None:
    config = _make_config(max_retries=3)
    client = ClobClient(config=config)
    call_count = 0

    def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
        nonlocal call_count
        call_count += 1
        bad_resp = MagicMock()
        bad_resp.status_code = 401
        raise httpx.HTTPStatusError("unauthorized", request=MagicMock(), response=bad_resp)

    with patch("httpx.Client") as mock_cls, patch("src.polymarket.client.time") as mock_time:
        mock_time.time.return_value = 1_000
        mock_time.sleep = MagicMock()
        mock_http = MagicMock()
        mock_cls.return_value.__enter__.return_value = mock_http
        mock_http.get.side_effect = side_effect

        with pytest.raises(httpx.HTTPStatusError):
            client.fetch_markets()

    # Should have tried only once — 4xx is not retried
    assert call_count == 1
