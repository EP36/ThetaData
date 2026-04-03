"""Factory helpers for selecting a market data provider from environment."""

from __future__ import annotations

import os

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
        api_key = os.getenv("ALPACA_API_KEY", os.getenv("BROKER_API_KEY", "")).strip()
        api_secret = os.getenv("ALPACA_API_SECRET", os.getenv("BROKER_API_SECRET", "")).strip()
        if not api_key or not api_secret:
            raise ValueError(
                "DATA_PROVIDER=alpaca requires ALPACA_API_KEY/ALPACA_API_SECRET "
                "(or BROKER_API_KEY/BROKER_API_SECRET)."
            )
        return AlpacaMarketDataProvider(
            api_key=api_key,
            api_secret=api_secret,
            base_url=os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets").strip(),
            feed=os.getenv("ALPACA_DATA_FEED", "iex").strip(),
        )

    raise ValueError(
        f"Unsupported DATA_PROVIDER '{provider_name}'. "
        "Expected one of: synthetic, alpaca"
    )
