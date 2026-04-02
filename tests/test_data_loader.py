"""Tests for market data loader."""

from __future__ import annotations

import pandas as pd
import pytest

from src.data.loader import MarketDataLoader


def test_generate_synthetic_ohlcv_shape_and_columns() -> None:
    loader = MarketDataLoader()
    data = loader.generate_synthetic_ohlcv(start="2025-01-01", periods=20)

    assert len(data) == 20
    assert list(data.columns) == ["open", "high", "low", "close", "volume"]


def test_load_csv_requires_timestamp_column(tmp_path) -> None:
    csv_path = tmp_path / "missing_timestamp.csv"
    pd.DataFrame(
        {
            "open": [1.0],
            "high": [1.1],
            "low": [0.9],
            "close": [1.0],
            "volume": [1000],
        }
    ).to_csv(csv_path, index=False)

    loader = MarketDataLoader()
    with pytest.raises(ValueError, match="timestamp"):
        loader.load_csv(csv_path)
