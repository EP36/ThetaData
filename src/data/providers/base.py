"""Provider interface for historical market data ingestion."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, slots=True)
class DataRequest:
    """Structured market data request."""

    symbol: str
    timeframe: str
    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None


class MarketDataProvider(ABC):
    """Abstract provider for OHLCV market data."""

    @abstractmethod
    def fetch_ohlcv(self, request: DataRequest) -> pd.DataFrame:
        """Fetch OHLCV data for a request.

        Return either:
        - DataFrame with `timestamp, open, high, low, close, volume` columns, or
        - DataFrame indexed by timestamp with OHLCV columns.
        """
        raise NotImplementedError
