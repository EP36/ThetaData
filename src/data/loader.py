"""Historical and synthetic market data loading utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass(slots=True)
class MarketDataLoader:
    """Loader for historical and synthetic OHLCV data."""

    timestamp_column: str = "timestamp"

    def load_csv(self, path: str | Path) -> pd.DataFrame:
        """Load historical OHLCV data from CSV.

        Expected columns:
            timestamp, open, high, low, close, volume

        Args:
            path: CSV file path.

        Returns:
            DataFrame indexed by timestamp.

        Raises:
            ValueError: If required columns are missing.
        """
        csv_path = Path(path)
        data = pd.read_csv(csv_path)

        if self.timestamp_column not in data.columns:
            raise ValueError(f"Missing timestamp column: '{self.timestamp_column}'")

        missing = [col for col in REQUIRED_COLUMNS if col not in data.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        data[self.timestamp_column] = pd.to_datetime(
            data[self.timestamp_column], errors="coerce"
        )
        if data[self.timestamp_column].isna().any():
            raise ValueError(f"Invalid timestamp values in '{self.timestamp_column}'")

        for column in REQUIRED_COLUMNS:
            data[column] = pd.to_numeric(data[column], errors="coerce")

        invalid_numeric = [col for col in REQUIRED_COLUMNS if data[col].isna().any()]
        if invalid_numeric:
            raise ValueError(
                f"Non-numeric values found in required columns: {invalid_numeric}"
            )

        data = data.set_index(self.timestamp_column).sort_index()
        if data.index.has_duplicates:
            raise ValueError("Duplicate timestamps found in market data")
        return data

    def generate_synthetic_ohlcv(
        self,
        start: str,
        periods: int = 252,
        freq: str = "D",
        start_price: float = 100.0,
        seed: int | None = 42,
    ) -> pd.DataFrame:
        """Generate synthetic OHLCV data for quick experiments.

        Args:
            start: Start timestamp accepted by pandas.
            periods: Number of rows to generate.
            freq: Frequency string (for example, "D" or "H").
            start_price: Initial close price.
            seed: Random seed for reproducibility.

        Returns:
            DataFrame indexed by timestamp with OHLCV columns.
        """
        if periods <= 0:
            raise ValueError("periods must be positive")
        if start_price <= 0:
            raise ValueError("start_price must be positive")

        rng = np.random.default_rng(seed)
        index = pd.date_range(start=start, periods=periods, freq=freq)

        returns = rng.normal(loc=0.0003, scale=0.01, size=periods)
        close = start_price * np.cumprod(1.0 + returns)

        open_ = np.roll(close, 1)
        open_[0] = close[0]

        high = np.maximum(open_, close) * (1.0 + rng.uniform(0.0005, 0.01, size=periods))
        low = np.minimum(open_, close) * (1.0 - rng.uniform(0.0005, 0.01, size=periods))
        volume = rng.integers(100_000, 500_000, size=periods)

        data = pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            },
            index=index,
        )
        data.index.name = self.timestamp_column
        return data
