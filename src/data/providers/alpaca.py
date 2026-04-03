"""Alpaca historical bars provider for OHLCV ingestion."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

import httpx
import pandas as pd

from src.data.providers.base import DataRequest, MarketDataProvider

LOGGER = logging.getLogger("theta.data.providers.alpaca")

_TIMEFRAME_MAP: dict[str, str] = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "30m": "30Min",
    "1h": "1Hour",
    "2h": "2Hour",
    "4h": "4Hour",
    "1d": "1Day",
}


@dataclass(slots=True)
class AlpacaMarketDataProvider(MarketDataProvider):
    """Fetch historical OHLCV bars from Alpaca Market Data API."""

    api_key: str
    api_secret: str
    base_url: str = "https://data.alpaca.markets"
    feed: str = "iex"
    timeout_seconds: float = 15.0
    max_bars_per_page: int = 10_000

    def __post_init__(self) -> None:
        """Validate provider configuration."""
        if not self.api_key.strip():
            raise ValueError("Alpaca api_key cannot be empty")
        if not self.api_secret.strip():
            raise ValueError("Alpaca api_secret cannot be empty")
        if not self.base_url.strip():
            raise ValueError("Alpaca base_url cannot be empty")
        if not self.feed.strip():
            raise ValueError("Alpaca feed cannot be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_bars_per_page <= 0:
            raise ValueError("max_bars_per_page must be positive")

    def fetch_ohlcv(self, request: DataRequest) -> pd.DataFrame:
        """Fetch OHLCV bars for one symbol and timeframe."""
        symbol = request.symbol.strip().upper()
        timeframe = request.timeframe.strip().lower()
        if not symbol:
            raise ValueError("symbol cannot be empty")
        if timeframe not in _TIMEFRAME_MAP:
            raise ValueError(
                f"Unsupported Alpaca timeframe '{request.timeframe}'. "
                f"Supported: {sorted(_TIMEFRAME_MAP)}"
            )

        start = (
            pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=365)
            if request.start is None
            else pd.Timestamp(request.start)
        )
        end = (
            pd.Timestamp.now(tz="UTC")
            if request.end is None
            else pd.Timestamp(request.end)
        )
        if end < start:
            raise ValueError("end must be greater than or equal to start")

        start_iso = start.tz_localize("UTC").isoformat() if start.tzinfo is None else start.isoformat()
        end_iso = end.tz_localize("UTC").isoformat() if end.tzinfo is None else end.isoformat()

        bars: list[dict[str, Any]] = []
        page_token: str | None = None
        timeframe_param = _TIMEFRAME_MAP[timeframe]

        with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            while True:
                params = {
                    "symbols": symbol,
                    "timeframe": timeframe_param,
                    "start": start_iso,
                    "end": end_iso,
                    "adjustment": "raw",
                    "feed": self.feed,
                    "sort": "asc",
                    "limit": str(self.max_bars_per_page),
                }
                if page_token:
                    params["page_token"] = page_token

                response = client.get(
                    "/v2/stocks/bars",
                    params=params,
                    headers={
                        "APCA-API-KEY-ID": self.api_key,
                        "APCA-API-SECRET-KEY": self.api_secret,
                    },
                )
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    detail = exc.response.text.strip() or str(exc)
                    raise RuntimeError(f"Alpaca bars request failed: {detail}") from exc

                payload = response.json()
                symbol_bars = payload.get("bars", {}).get(symbol, [])
                if isinstance(symbol_bars, list):
                    bars.extend(symbol_bars)

                page_token = payload.get("next_page_token")
                if not page_token:
                    break

        if not bars:
            raise ValueError(
                f"No Alpaca bars returned for {symbol} ({request.timeframe}) "
                f"between {start_iso} and {end_iso}"
            )

        frame = pd.DataFrame(
            {
                "timestamp": [bar.get("t") for bar in bars],
                "open": [bar.get("o") for bar in bars],
                "high": [bar.get("h") for bar in bars],
                "low": [bar.get("l") for bar in bars],
                "close": [bar.get("c") for bar in bars],
                "volume": [bar.get("v") for bar in bars],
            }
        )
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        LOGGER.info(
            "alpaca_bars_fetched symbol=%s timeframe=%s rows=%d",
            symbol,
            request.timeframe,
            len(frame),
        )
        return frame
