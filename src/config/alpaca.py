"""Canonical Alpaca environment variable helpers."""

from __future__ import annotations

import os

DEFAULT_ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"
DEFAULT_ALPACA_DATA_FEED = "iex"
DEFAULT_ALPACA_BASE_URL = "https://paper-api.alpaca.markets"


def read_alpaca_api_key() -> str:
    """Read canonical Alpaca API key."""
    return os.getenv("ALPACA_API_KEY", "").strip()


def read_alpaca_api_secret() -> str:
    """Read canonical Alpaca API secret with temporary legacy fallback."""
    secret = os.getenv("ALPACA_API_SECRET", "").strip()
    if secret:
        return secret
    # Backward-compatibility alias; canonical name is ALPACA_API_SECRET.
    return os.getenv("ALPACA_SECRET_KEY", "").strip()


def read_alpaca_data_base_url() -> str:
    """Read Alpaca market-data base URL."""
    return os.getenv("ALPACA_DATA_BASE_URL", DEFAULT_ALPACA_DATA_BASE_URL).strip()


def read_alpaca_data_feed() -> str:
    """Read Alpaca market-data feed selector."""
    return os.getenv("ALPACA_DATA_FEED", DEFAULT_ALPACA_DATA_FEED).strip()


def read_alpaca_execution_base_url() -> str:
    """Read Alpaca execution base URL (paper/live endpoint host)."""
    return os.getenv("ALPACA_BASE_URL", DEFAULT_ALPACA_BASE_URL).strip()
