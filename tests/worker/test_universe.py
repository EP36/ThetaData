"""Tests for worker universe scanning, filtering, and ranking."""

from __future__ import annotations

import pandas as pd

from src.worker.universe import UniverseScanner, UniverseScannerConfig


class StubLoader:
    """Minimal loader stub returning preconfigured frames by symbol."""

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def load(  # noqa: D401
        self,
        symbol: str,
        timeframe: str,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        if symbol not in self.frames:
            raise ValueError("symbol missing")
        return self.frames[symbol].copy()


def make_frame(
    close_values: list[float],
    volume_values: list[float],
    freq: str = "D",
    bid_ask: tuple[float, float] | None = None,
) -> pd.DataFrame:
    """Create deterministic OHLCV frame for scanner tests."""
    index = pd.date_range("2026-01-01", periods=len(close_values), freq=freq)
    close = pd.Series(close_values, index=index, dtype=float)
    frame = pd.DataFrame(
        {
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": pd.Series(volume_values, index=index, dtype=float),
        },
        index=index,
    )
    if bid_ask is not None:
        bid, ask = bid_ask
        frame["bid"] = float(bid)
        frame["ask"] = float(ask)
    return frame


def test_static_mode_applies_filters_and_shortlist_limit() -> None:
    scanner = UniverseScanner(
        loader=StubLoader(
            {
                "AAA": make_frame([10, 10.5, 11], [200_000, 220_000, 250_000]),
                "BBB": make_frame([0.8, 0.85, 0.9], [500_000, 500_000, 500_000]),
                "CCC": make_frame([15, 15.1, 15.2], [100, 120, 130]),
            }
        ),
        config=UniverseScannerConfig(
            timeframe="1d",
            max_candidates=2,
            min_price=1.0,
            min_average_volume=1_000.0,
            min_relative_volume=0.0,
            max_spread_pct=1.0,
        ),
    )

    result = scanner.scan(
        mode="static",
        configured_symbols=("AAA", "BBB", "CCC"),
        now=pd.Timestamp("2026-02-01", tz="UTC"),
    )
    assert result.shortlisted_symbols == ("AAA",)
    assert "BBB" in result.filtered_out_reasons
    assert "below_min_price" in result.filtered_out_reasons["BBB"]
    assert "CCC" in result.filtered_out_reasons
    assert "below_min_avg_volume" in result.filtered_out_reasons["CCC"]


def test_top_gainers_and_losers_modes_rank_deterministically() -> None:
    loader = StubLoader(
        {
            "AAA": make_frame([10, 11], [100_000, 110_000]),
            "BBB": make_frame([10, 9], [100_000, 120_000]),
            "CCC": make_frame([10, 10.3], [100_000, 140_000]),
        }
    )
    config = UniverseScannerConfig(
        timeframe="1d",
        max_candidates=3,
        min_price=1.0,
        min_average_volume=0.0,
        min_relative_volume=0.0,
        max_spread_pct=1.0,
    )

    gainers = UniverseScanner(loader=loader, config=config).scan(
        mode="top_gainers",
        configured_symbols=("AAA", "BBB", "CCC"),
        now=pd.Timestamp("2026-02-01", tz="UTC"),
    )
    losers = UniverseScanner(loader=loader, config=config).scan(
        mode="top_losers",
        configured_symbols=("AAA", "BBB", "CCC"),
        now=pd.Timestamp("2026-02-01", tz="UTC"),
    )

    assert gainers.shortlisted_symbols[0] == "AAA"
    assert losers.shortlisted_symbols[0] == "BBB"


def test_high_relative_volume_ranking_marks_rank_cutoff() -> None:
    scanner = UniverseScanner(
        loader=StubLoader(
            {
                "AAA": make_frame([10, 10], [100_000, 300_000]),  # rv ~1.5
                "BBB": make_frame([10, 10], [100_000, 200_000]),  # rv ~1.33
                "CCC": make_frame([10, 10], [100_000, 110_000]),  # rv ~1.05
            }
        ),
        config=UniverseScannerConfig(
            timeframe="1d",
            max_candidates=2,
            min_price=1.0,
            min_average_volume=0.0,
            min_relative_volume=0.0,
            max_spread_pct=1.0,
        ),
    )

    result = scanner.scan(
        mode="high_relative_volume",
        configured_symbols=("AAA", "BBB", "CCC"),
        now=pd.Timestamp("2026-02-01", tz="UTC"),
    )
    assert result.shortlisted_symbols == ("AAA", "BBB")
    assert "CCC" in result.filtered_out_reasons
    assert "ranked_outside_max_candidates" in result.filtered_out_reasons["CCC"]


def test_spread_filter_blocks_wide_spread_when_quote_data_present() -> None:
    scanner = UniverseScanner(
        loader=StubLoader(
            {"AAA": make_frame([10, 10.2], [200_000, 210_000], bid_ask=(9.0, 11.0))}
        ),
        config=UniverseScannerConfig(
            timeframe="1d",
            max_candidates=5,
            min_price=1.0,
            min_average_volume=0.0,
            min_relative_volume=0.0,
            max_spread_pct=0.05,
        ),
    )

    result = scanner.scan(
        mode="static",
        configured_symbols=("AAA",),
        now=pd.Timestamp("2026-02-01", tz="UTC"),
    )
    assert result.shortlisted_symbols == ()
    assert "AAA" in result.filtered_out_reasons
    assert "spread_above_max" in result.filtered_out_reasons["AAA"]


def test_intraday_stale_data_is_excluded() -> None:
    stale_index = pd.date_range("2026-01-01", periods=3, freq="min")
    stale = pd.DataFrame(
        {
            "open": [10.0, 10.1, 10.2],
            "high": [10.1, 10.2, 10.3],
            "low": [9.9, 10.0, 10.1],
            "close": [10.0, 10.1, 10.2],
            "volume": [100_000.0, 110_000.0, 120_000.0],
        },
        index=stale_index,
    )
    scanner = UniverseScanner(
        loader=StubLoader({"AAA": stale}),
        config=UniverseScannerConfig(
            timeframe="1m",
            max_candidates=5,
            min_price=1.0,
            min_average_volume=0.0,
            min_relative_volume=0.0,
            max_spread_pct=1.0,
        ),
    )

    result = scanner.scan(
        mode="static",
        configured_symbols=("AAA",),
        now=pd.Timestamp("2026-01-02T12:00:00Z"),
    )
    assert result.shortlisted_symbols == ()
    assert "AAA" in result.filtered_out_reasons
    assert "stale_market_data" in result.filtered_out_reasons["AAA"]
