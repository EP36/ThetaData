"""Tests for Polymarket market token discovery and orderbook scanning."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from src.polymarket.scanner import fetch_btc_markets, fetch_market_orderbooks


class FakeClobClient:
    """Minimal fake for scanner tests."""

    def __init__(
        self,
        pages: list[dict[str, Any]],
        parent_by_token: dict[str, dict[str, Any] | Exception] | None = None,
    ) -> None:
        self.pages = pages
        self.parent_by_token = parent_by_token or {}
        self.book_tokens: list[str] = []

    def fetch_markets(self, next_cursor: str = "") -> dict[str, Any]:
        del next_cursor
        return self.pages.pop(0)

    def fetch_market_by_token(self, token_id: str) -> dict[str, Any]:
        parent = self.parent_by_token.get(token_id)
        if isinstance(parent, Exception):
            raise parent
        if parent is None:
            raise RuntimeError("404")
        return parent

    def fetch_orderbook(self, token_id: str) -> dict[str, Any]:
        self.book_tokens.append(token_id)
        return {
            "bids": [{"price": "0.40", "size": "10"}],
            "asks": [{"price": "0.45", "size": "10"}],
        }


def _page(raw: dict[str, Any]) -> dict[str, Any]:
    return {"data": [raw], "next_cursor": "LTE="}


def _parent(
    *,
    condition_id: str = "cond-1",
    yes_token: str = "yes-token",
    no_token: str = "no-token",
) -> dict[str, Any]:
    return {
        "condition_id": condition_id,
        "primary_token_id": yes_token,
        "secondary_token_id": no_token,
    }


def _market_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "condition_id": "cond-1",
        "market_id": "market-1",
        "question": "Will BTC be above $100k?",
        "active": True,
        "closed": False,
        "archived": False,
        "accepting_orders": True,
        "enable_order_book": True,
        "tokens": [
            {"outcome": "Yes", "token_id": "yes-token"},
            {"outcome": "No", "token_id": "no-token"},
        ],
    }
    payload.update(overrides)
    return payload


def test_valid_token_id_reaches_orderbook() -> None:
    client = FakeClobClient(
        pages=[_page(_market_payload())],
        parent_by_token={"yes-token": _parent()},
    )

    markets = fetch_btc_markets(client)  # type: ignore[arg-type]
    orderbooks = fetch_market_orderbooks(client, markets)  # type: ignore[arg-type]

    assert client.book_tokens == ["yes-token", "no-token"]
    assert len(orderbooks) == 1
    assert orderbooks[0].market.condition_id == "cond-1"


def test_asset_id_tokens_are_used_directly_for_orderbook() -> None:
    client = FakeClobClient(
        pages=[
            _page(
                _market_payload(
                    tokens=[
                        {"outcome": "Yes", "asset_id": "yes-asset"},
                        {"outcome": "No", "asset_id": "no-asset"},
                    ]
                )
            )
        ],
        parent_by_token={
            "yes-asset": _parent(yes_token="yes-asset", no_token="no-asset")
        },
    )

    markets = fetch_btc_markets(client)  # type: ignore[arg-type]
    orderbooks = fetch_market_orderbooks(client, markets)  # type: ignore[arg-type]

    assert client.book_tokens == ["yes-asset", "no-asset"]
    assert len(orderbooks) == 1
    assert orderbooks[0].market.yes_token.source_key == "asset_id"


def test_invalid_token_lookup_is_skipped_before_orderbook(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="theta.polymarket.scanner")
    client = FakeClobClient(
        pages=[_page(_market_payload())],
        parent_by_token={"yes-token": RuntimeError("404")},
    )

    markets = fetch_btc_markets(client)  # type: ignore[arg-type]
    orderbooks = fetch_market_orderbooks(client, markets)  # type: ignore[arg-type]

    assert orderbooks == []
    assert client.book_tokens == []
    assert "reason=token_lookup_failed" in caplog.text


def test_stale_no_token_is_skipped_before_orderbook(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="theta.polymarket.scanner")
    client = FakeClobClient(
        pages=[_page(_market_payload())],
        parent_by_token={"yes-token": _parent(no_token="fresh-no-token")},
    )

    markets = fetch_btc_markets(client)  # type: ignore[arg-type]
    orderbooks = fetch_market_orderbooks(client, markets)  # type: ignore[arg-type]

    assert orderbooks == []
    assert client.book_tokens == []
    assert "reason=no_token_not_secondary" in caplog.text


def test_condition_id_is_never_used_as_token_id() -> None:
    client = FakeClobClient(
        pages=[
            _page(
                _market_payload(
                    tokens=[
                        {"outcome": "Yes", "token_id": "cond-1"},
                        {"outcome": "No", "token_id": "no-token"},
                    ]
                )
            )
        ],
        parent_by_token={"cond-1": _parent(yes_token="cond-1")},
    )

    markets = fetch_btc_markets(client)  # type: ignore[arg-type]
    orderbooks = fetch_market_orderbooks(client, markets)  # type: ignore[arg-type]

    assert markets == []
    assert orderbooks == []
    assert client.book_tokens == []


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"active": False}, "inactive_market"),
        ({"closed": True}, "closed_market"),
        ({"accepting_orders": False}, "not_accepting_orders"),
        ({"enable_order_book": False}, "orderbook_disabled"),
    ],
)
def test_closed_or_non_book_markets_are_filtered_before_orderbook(
    overrides: dict[str, Any],
    reason: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="theta.polymarket.scanner")
    client = FakeClobClient(
        pages=[_page(_market_payload(**overrides))],
        parent_by_token={"yes-token": _parent()},
    )

    markets = fetch_btc_markets(client)  # type: ignore[arg-type]
    orderbooks = fetch_market_orderbooks(client, markets)  # type: ignore[arg-type]

    assert markets == []
    assert orderbooks == []
    assert client.book_tokens == []
    assert f"reason={reason}" in caplog.text
