"""Tests for data ingestion loader, normalization, and cache behavior."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.data.cache import DataCache
from src.data.loaders import HistoricalDataLoader
from src.data.providers.base import DataRequest, MarketDataProvider


@dataclass
class StubProvider(MarketDataProvider):
    """Provider stub for deterministic ingestion tests."""

    frame: pd.DataFrame
    calls: int = 0

    def fetch_ohlcv(self, request: DataRequest) -> pd.DataFrame:
        self.calls += 1
        _ = request
        return self.frame.copy()


class FlakyProvider(MarketDataProvider):
    """Provider that fails once then succeeds to test retry behavior."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls = 0

    def fetch_ohlcv(self, request: DataRequest) -> pd.DataFrame:
        self.calls += 1
        _ = request
        if self.calls == 1:
            raise RuntimeError("temporary fetch failure")
        return self.frame.copy()


def make_raw_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [
                "2025-01-01",
                "2025-01-01",  # duplicate timestamp
                "2025-01-02",
                "bad-date",  # invalid timestamp row should be dropped
            ],
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [101.0, 102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0, 102.0],
            "close": [100.5, 101.5, 102.5, 103.5],
            "volume": [1000, 1100, 1200, 1300],
        }
    )


def test_normalization_handles_duplicates_and_invalid_rows(tmp_path) -> None:
    provider = StubProvider(frame=make_raw_frame())
    loader = HistoricalDataLoader(provider=provider, cache=DataCache(root_dir=tmp_path / "cache"))

    data = loader.load(symbol="AAPL", timeframe="1d", force_refresh=True)

    # duplicate + bad timestamp row removed; two valid rows remain
    assert len(data) == 2
    assert list(data.columns) == ["open", "high", "low", "close", "volume"]
    assert data.index.is_monotonic_increasing


def test_cache_hit_prevents_provider_refetch(tmp_path) -> None:
    provider = StubProvider(frame=make_raw_frame())
    cache = DataCache(root_dir=tmp_path / "cache")
    loader = HistoricalDataLoader(provider=provider, cache=cache)

    loader.load(symbol="AAPL", timeframe="1d", force_refresh=True)
    assert provider.calls == 1

    loader.load(symbol="AAPL", timeframe="1d", force_refresh=False)
    assert provider.calls == 1


def test_cache_miss_fetches_and_persists(tmp_path) -> None:
    provider = StubProvider(frame=make_raw_frame())
    cache = DataCache(root_dir=tmp_path / "cache")
    loader = HistoricalDataLoader(provider=provider, cache=cache)

    data = loader.load(symbol="MSFT", timeframe="1h", force_refresh=False)

    assert provider.calls == 1
    assert cache.exists(symbol="MSFT", timeframe="1h")
    assert not data.empty


def test_provider_retry_behavior(tmp_path) -> None:
    provider = FlakyProvider(frame=make_raw_frame())
    loader = HistoricalDataLoader(
        provider=provider,
        cache=DataCache(root_dir=tmp_path / "cache"),
        max_retries=2,
        retry_delay_seconds=0.0,
    )

    data = loader.load(symbol="NVDA", timeframe="1d", force_refresh=True)

    assert provider.calls == 2
    assert not data.empty


def test_load_by_date_range_filters_rows(tmp_path) -> None:
    provider = StubProvider(frame=make_raw_frame())
    loader = HistoricalDataLoader(provider=provider, cache=DataCache(root_dir=tmp_path / "cache"))

    data = loader.load(
        symbol="SPY",
        timeframe="1d",
        start="2025-01-02",
        end="2025-01-02",
        force_refresh=True,
    )

    assert len(data) == 1
    assert data.index.min() == pd.Timestamp("2025-01-02")


def test_cache_range_miss_refetches_provider(tmp_path) -> None:
    cache = DataCache(root_dir=tmp_path / "cache")
    stale_cached = pd.DataFrame(
        {
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [1000.0, 1100.0],
        },
        index=pd.DatetimeIndex([pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")], name="timestamp"),
    )
    cache.save(symbol="SPY", timeframe="1d", data=stale_cached)

    fresh_provider_frame = pd.DataFrame(
        {
            "timestamp": ["2025-01-01", "2025-01-02"],
            "open": [200.0, 201.0],
            "high": [202.0, 203.0],
            "low": [199.0, 200.0],
            "close": [201.0, 202.0],
            "volume": [5000, 6000],
        }
    )
    provider = StubProvider(frame=fresh_provider_frame)
    loader = HistoricalDataLoader(provider=provider, cache=cache)

    data = loader.load(
        symbol="SPY",
        timeframe="1d",
        start="2025-01-01",
        end="2025-01-02",
        force_refresh=False,
    )

    assert provider.calls == 1
    assert len(data) == 2
    assert data.index.min() == pd.Timestamp("2025-01-01")


def test_load_handles_tz_aware_index_with_naive_request_range(tmp_path) -> None:
    provider = StubProvider(
        frame=pd.DataFrame(
            {
                "timestamp": [
                    pd.Timestamp("2025-01-01T00:00:00Z"),
                    pd.Timestamp("2025-01-02T00:00:00Z"),
                ],
                "open": [100.0, 101.0],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.5, 101.5],
                "volume": [1000, 1100],
            }
        )
    )
    loader = HistoricalDataLoader(provider=provider, cache=DataCache(root_dir=tmp_path / "cache"))

    data = loader.load(
        symbol="SPY",
        timeframe="1d",
        start="2025-01-02",
        end="2025-01-02",
        force_refresh=True,
    )

    assert len(data) == 1
