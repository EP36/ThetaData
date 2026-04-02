"""Historical data ingestion, normalization, retry, and caching."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time

import pandas as pd

from src.data.cache import DataCache
from src.data.providers.base import DataRequest, MarketDataProvider

REQUIRED_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")
NORMALIZED_COLUMNS = ("timestamp",) + REQUIRED_OHLCV_COLUMNS
LOGGER = logging.getLogger("theta.data.loaders")


@dataclass(slots=True)
class HistoricalDataLoader:
    """Load normalized OHLCV data via provider + local cache."""

    provider: MarketDataProvider
    cache: DataCache
    max_retries: int = 3
    retry_delay_seconds: float = 0.0

    def __post_init__(self) -> None:
        """Validate loader parameters."""
        if self.max_retries <= 0:
            raise ValueError("max_retries must be positive")
        if self.retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds cannot be negative")

    def load(
        self,
        symbol: str,
        timeframe: str,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Load normalized OHLCV data by symbol/timeframe/date range."""
        LOGGER.info(
            "data_load_start symbol=%s timeframe=%s start=%s end=%s force_refresh=%s",
            symbol,
            timeframe,
            start,
            end,
            force_refresh,
        )
        start_ts = pd.to_datetime(start) if start is not None else None
        end_ts = pd.to_datetime(end) if end is not None else None

        cached = None
        if not force_refresh:
            cached = self.cache.load(symbol=symbol, timeframe=timeframe)
        if cached is not None:
            LOGGER.info(
                "data_cache_hit symbol=%s timeframe=%s rows=%d",
                symbol,
                timeframe,
                len(cached),
            )
            return self._slice_range(cached, start=start_ts, end=end_ts)
        LOGGER.info("data_cache_miss symbol=%s timeframe=%s", symbol, timeframe)

        request = DataRequest(symbol=symbol, timeframe=timeframe, start=start_ts, end=end_ts)

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                LOGGER.info(
                    "data_provider_fetch symbol=%s timeframe=%s attempt=%d",
                    symbol,
                    timeframe,
                    attempt,
                )
                raw_data = self.provider.fetch_ohlcv(request)
                normalized = self.normalize_ohlcv(raw_data)
                self.cache.save(symbol=symbol, timeframe=timeframe, data=normalized)
                LOGGER.info(
                    "data_load_complete symbol=%s timeframe=%s rows=%d",
                    symbol,
                    timeframe,
                    len(normalized),
                )
                return self._slice_range(normalized, start=start_ts, end=end_ts)
            except Exception as exc:  # pragma: no cover - retry branch asserted via behavior
                last_error = exc
                LOGGER.warning(
                    "data_provider_error symbol=%s timeframe=%s attempt=%d error=%s",
                    symbol,
                    timeframe,
                    attempt,
                    exc,
                )
                if attempt == self.max_retries:
                    break
                if self.retry_delay_seconds > 0:
                    time.sleep(self.retry_delay_seconds)

        assert last_error is not None
        raise RuntimeError(
            f"Failed to load data for {symbol} ({timeframe}) after {self.max_retries} attempts"
        ) from last_error

    def normalize_ohlcv(self, raw_data: pd.DataFrame) -> pd.DataFrame:
        """Normalize provider output to timestamp-indexed OHLCV frame."""
        frame = raw_data.copy()

        if "timestamp" not in frame.columns:
            if isinstance(frame.index, pd.DatetimeIndex):
                frame = frame.reset_index().rename(columns={frame.index.name or "index": "timestamp"})
            else:
                raise ValueError("Raw data must include a timestamp column or DatetimeIndex")

        missing = [col for col in REQUIRED_OHLCV_COLUMNS if col not in frame.columns]
        if missing:
            raise ValueError(f"Raw data missing required OHLCV columns: {missing}")

        frame = frame.loc[:, NORMALIZED_COLUMNS].copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")

        for column in REQUIRED_OHLCV_COLUMNS:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

        frame = frame.dropna(subset=list(NORMALIZED_COLUMNS))
        if frame.empty:
            raise ValueError("No valid rows after normalization")

        frame = frame.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp")
        frame = frame.set_index("timestamp")

        return frame

    @staticmethod
    def _slice_range(
        data: pd.DataFrame,
        start: pd.Timestamp | None,
        end: pd.Timestamp | None,
    ) -> pd.DataFrame:
        """Return date-filtered data without mutating source."""
        sliced = data
        if start is not None:
            sliced = sliced.loc[sliced.index >= start]
        if end is not None:
            sliced = sliced.loc[sliced.index <= end]
        return sliced.copy()
