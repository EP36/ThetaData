"""Historical data fetcher for backtests.

Fetches bars from Alpaca (equities) or loads from a user-provided JSON file
(Polymarket — no historical API). Never touches live broker execution.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

LOGGER = logging.getLogger("trauto.backtester.data_loader")


def load_alpaca_bars(
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    api_key: str = "",
    api_secret: str = "",
    data_base_url: str = "https://data.alpaca.markets",
    limit: int = 10000,
) -> pd.DataFrame:
    """Fetch historical OHLCV bars from Alpaca data API.

    Returns a DataFrame indexed by timestamp with columns:
    open, high, low, close, volume.
    Returns empty DataFrame if credentials are missing or request fails.
    """
    if not api_key or not api_secret:
        try:
            from src.config.alpaca import read_alpaca_api_key, read_alpaca_api_secret, read_alpaca_data_base_url
            api_key = api_key or read_alpaca_api_key()
            api_secret = api_secret or read_alpaca_api_secret()
            data_base_url = data_base_url or read_alpaca_data_base_url()
        except Exception:
            pass

    if not api_key or not api_secret:
        LOGGER.warning("alpaca_bars_no_credentials symbol=%s", symbol)
        return pd.DataFrame()

    import httpx
    try:
        with httpx.Client(base_url=data_base_url, timeout=30.0) as client:
            resp = client.get(
                "/v2/stocks/bars",
                params={
                    "symbols": symbol,
                    "timeframe": timeframe,
                    "start": start,
                    "end": end,
                    "limit": limit,
                    "sort": "asc",
                    "feed": "iex",
                },
                headers={
                    "APCA-API-KEY-ID": api_key,
                    "APCA-API-SECRET-KEY": api_secret,
                },
            )
            resp.raise_for_status()
    except Exception as exc:
        LOGGER.warning("alpaca_bars_fetch_failed symbol=%s error=%s", symbol, exc)
        return pd.DataFrame()

    raw = resp.json()
    bars = raw.get("bars", {}).get(symbol, [])
    if not bars:
        LOGGER.info("alpaca_bars_empty symbol=%s start=%s end=%s", symbol, start, end)
        return pd.DataFrame()

    df = pd.DataFrame([
        {
            "timestamp": b.get("t", ""),
            "open": float(b.get("o", 0)),
            "high": float(b.get("h", 0)),
            "low": float(b.get("l", 0)),
            "close": float(b.get("c", 0)),
            "volume": float(b.get("v", 0)),
        }
        for b in bars
    ])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    LOGGER.info("alpaca_bars_loaded symbol=%s bars=%d", symbol, len(df))
    return df


def load_polymarket_history(path: str | Path) -> list[dict[str, Any]]:
    """Load user-provided historical Polymarket market data from a JSON file.

    Expected format:
    [
      {
        "condition_id": "...",
        "market_question": "...",
        "yes_prices": [{"timestamp": "...", "price": 0.55}, ...],
        "resolved_outcome": "YES" | "NO" | null
      },
      ...
    ]

    Returns an empty list if the file is missing or malformed.
    """
    fpath = Path(path)
    if not fpath.exists():
        LOGGER.warning("polymarket_history_not_found path=%s", path)
        return []
    try:
        data = json.loads(fpath.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            LOGGER.warning("polymarket_history_invalid_format path=%s", path)
            return []
        LOGGER.info("polymarket_history_loaded path=%s markets=%d", path, len(data))
        return data
    except Exception as exc:
        LOGGER.warning("polymarket_history_load_failed path=%s error=%s", path, exc)
        return []
