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
        provider_name = type(self.provider).__name__
        LOGGER.info(
            "data_provider_selected provider=%s symbol=%s timeframe=%s",
            provider_name,
            symbol,
            timeframe,
        )
        LOGGER.info(
            "data_load_start provider=%s symbol=%s timeframe=%s start=%s end=%s force_refresh=%s",
            provider_name,
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
            sliced_cached = self._slice_range(cached, start=start_ts, end=end_ts)
            cache_covers_range = self._cache_covers_requested_range(
                cached=cached,
                start=start_ts,
                end=end_ts,
            )
            if cache_covers_range and not sliced_cached.empty:
                LOGGER.info(
                    "data_cache_hit provider=%s symbol=%s timeframe=%s cached_rows=%d sliced_rows=%d",
                    provider_name,
                    symbol,
                    timeframe,
                    len(cached),
                    len(sliced_cached),
                )
                return sliced_cached

            cache_min = pd.Timestamp(cached.index.min()) if not cached.empty else None
            cache_max = pd.Timestamp(cached.index.max()) if not cached.empty else None
            LOGGER.info(
                "data_cache_range_miss provider=%s symbol=%s timeframe=%s cached_rows=%d sliced_rows=%d cache_start=%s cache_end=%s request_start=%s request_end=%s",
                provider_name,
                symbol,
                timeframe,
                len(cached),
                len(sliced_cached),
                cache_min,
                cache_max,
                start_ts,
                end_ts,
            )
        LOGGER.info(
            "data_cache_miss provider=%s symbol=%s timeframe=%s",
            provider_name,
            symbol,
            timeframe,
        )

        request = DataRequest(symbol=symbol, timeframe=timeframe, start=start_ts, end=end_ts)

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                LOGGER.info(
                    "data_provider_fetch provider=%s symbol=%s timeframe=%s attempt=%d start=%s end=%s",
                    provider_name,
                    symbol,
                    timeframe,
                    attempt,
                    start_ts,
                    end_ts,
                )
                raw_data = self.provider.fetch_ohlcv(request)
                LOGGER.info(
                    "data_provider_response provider=%s symbol=%s timeframe=%s raw_rows=%d",
                    provider_name,
                    symbol,
                    timeframe,
                    len(raw_data),
                )
                normalized = self.normalize_ohlcv(raw_data)
                LOGGER.info(
                    "data_normalized provider=%s symbol=%s timeframe=%s normalized_rows=%d",
                    provider_name,
                    symbol,
                    timeframe,
                    len(normalized),
                )
                sliced = self._slice_range(normalized, start=start_ts, end=end_ts)
                if sliced.empty:
                    raise ValueError(
                        "No market data rows available after normalization and date filtering "
                        f"for {symbol} ({timeframe}) start={start_ts} end={end_ts}."
                    )
                self.cache.save(symbol=symbol, timeframe=timeframe, data=normalized)
                LOGGER.info(
                    "data_load_complete provider=%s symbol=%s timeframe=%s rows=%d",
                    provider_name,
                    symbol,
                    timeframe,
                    len(sliced),
                )
                return sliced
            except Exception as exc:  # pragma: no cover - retry branch asserted via behavior
                last_error = exc
                LOGGER.warning(
                    "data_provider_error provider=%s symbol=%s timeframe=%s attempt=%d error=%s",
                    provider_name,
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
        aligned_start = HistoricalDataLoader._align_timestamp_timezone(
            timestamp=start,
            index=data.index,
        )
        aligned_end = HistoricalDataLoader._align_timestamp_timezone(
            timestamp=end,
            index=data.index,
        )
        sliced = data
        if aligned_start is not None:
            sliced = sliced.loc[sliced.index >= aligned_start]
        if aligned_end is not None:
            sliced = sliced.loc[sliced.index <= aligned_end]
        return sliced.copy()

    @staticmethod
    def _cache_covers_requested_range(
        cached: pd.DataFrame,
        start: pd.Timestamp | None,
        end: pd.Timestamp | None,
    ) -> bool:
        """Return True when cached data fully covers requested date range."""
        if cached.empty:
            return False
        aligned_start = HistoricalDataLoader._align_timestamp_timezone(
            timestamp=start,
            index=cached.index,
        )
        aligned_end = HistoricalDataLoader._align_timestamp_timezone(
            timestamp=end,
            index=cached.index,
        )
        cache_start = pd.Timestamp(cached.index.min())
        cache_end = pd.Timestamp(cached.index.max())
        if aligned_start is not None and cache_start > aligned_start:
            return False
        if aligned_end is not None and cache_end < aligned_end:
            return False
        return True

    @staticmethod
    def _align_timestamp_timezone(
        timestamp: pd.Timestamp | None,
        index: pd.Index,
    ) -> pd.Timestamp | None:
        """Align timestamp timezone semantics with DatetimeIndex for safe comparison."""
        if timestamp is None:
            return None
        aligned = pd.Timestamp(timestamp)
        if not isinstance(index, pd.DatetimeIndex):
            return aligned
        index_tz = index.tz
        if index_tz is None:
            if aligned.tzinfo is not None:
                return aligned.tz_localize(None)
            return aligned
        if aligned.tzinfo is None:
            return aligned.tz_localize(index_tz)
        return aligned.tz_convert(index_tz)
