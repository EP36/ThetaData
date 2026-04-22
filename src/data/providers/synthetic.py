"""Synthetic market data provider for local workflows and tests."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.data.loader import MarketDataLoader
from src.data.providers.base import DataRequest, MarketDataProvider

TIMEFRAME_TO_FREQ = {
    "1d": "D",
    "4h": "4h",
    "2h": "2h",
    "1h": "h",
    "1m": "min",
}


@dataclass(slots=True)
class SyntheticMarketDataProvider(MarketDataProvider):
    """Provider that returns deterministic synthetic OHLCV data."""

    seed: int | None = 42
    default_periods: int = 252
    start_price: float = 100.0

    def fetch_ohlcv(self, request: DataRequest) -> pd.DataFrame:
        """Return generated OHLCV data for requested range."""
        if request.timeframe not in TIMEFRAME_TO_FREQ:
            raise ValueError(f"Unsupported synthetic timeframe: {request.timeframe}")

        freq = TIMEFRAME_TO_FREQ[request.timeframe]
        start = request.start or pd.Timestamp("2024-01-01")
        end = request.end
        periods = self.default_periods
        if end is not None and end >= start:
            periods = len(pd.date_range(start=start, end=end, freq=freq))
            periods = max(periods, 1)

        loader = MarketDataLoader()
        frame = loader.generate_synthetic_ohlcv(
            start=str(start),
            periods=periods,
            freq=freq,
            start_price=self.start_price,
            seed=self.seed,
        )
        return frame.reset_index().rename(columns={"timestamp": "timestamp"})
