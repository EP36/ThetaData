"""Factory helpers for selecting a market data provider from environment."""

from __future__ import annotations

import os

from src.config.alpaca import (
    read_alpaca_api_key,
    read_alpaca_api_secret,
    read_alpaca_data_base_url,
    read_alpaca_data_feed,
)
from src.data.providers.alpaca import AlpacaMarketDataProvider
from src.data.providers.base import MarketDataProvider
from src.data.providers.synthetic import SyntheticMarketDataProvider


def make_market_data_provider_from_env() -> MarketDataProvider:
    """Build a market data provider using DATA_PROVIDER selection.

    Supported values:
    - synthetic (default)
    - alpaca
    """
    provider_name = os.getenv("DATA_PROVIDER", "synthetic").strip().lower()
    if provider_name == "synthetic":
        return SyntheticMarketDataProvider()

    if provider_name == "alpaca":
        api_key = read_alpaca_api_key()
        api_secret = read_alpaca_api_secret()
        if not api_key or not api_secret:
            raise ValueError(
                "DATA_PROVIDER=alpaca requires ALPACA_API_KEY and "
                "ALPACA_API_SECRET (ALPACA_SECRET_KEY accepted temporarily). "
                "Set these environment variables on the web service for /api/backtests/run."
            )
        return AlpacaMarketDataProvider(
            api_key=api_key,
            api_secret=api_secret,
            base_url=read_alpaca_data_base_url(),
            feed=read_alpaca_data_feed(),
        )

    raise ValueError(
        f"Unsupported DATA_PROVIDER '{provider_name}'. "
        "Expected one of: synthetic, alpaca"
    )
