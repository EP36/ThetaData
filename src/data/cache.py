"""Local parquet cache for normalized OHLCV data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(slots=True)
class DataCache:
    """Cache normalized OHLCV data by symbol/timeframe."""

    root_dir: Path = Path("data/cache")

    def cache_path(self, symbol: str, timeframe: str) -> Path:
        """Return cache path for symbol/timeframe."""
        safe_symbol = symbol.replace("/", "_").upper()
        safe_timeframe = timeframe.replace("/", "_").lower()
        return self.root_dir / safe_symbol / f"{safe_timeframe}.parquet"

    def exists(self, symbol: str, timeframe: str) -> bool:
        """Return whether cache exists for symbol/timeframe."""
        return self.cache_path(symbol=symbol, timeframe=timeframe).exists()

    def load(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        """Load cached OHLCV data if available."""
        path = self.cache_path(symbol=symbol, timeframe=timeframe)
        if not path.exists():
            return None

        data = pd.read_parquet(path)
        if "timestamp" not in data.columns:
            raise ValueError(f"Cache file missing timestamp column: {path}")

        data["timestamp"] = pd.to_datetime(data["timestamp"], errors="coerce")
        if data["timestamp"].isna().any():
            raise ValueError(f"Cache file contains invalid timestamps: {path}")

        return data.set_index("timestamp").sort_index()

    def save(self, symbol: str, timeframe: str, data: pd.DataFrame) -> Path:
        """Persist normalized OHLCV data to parquet cache."""
        path = self.cache_path(symbol=symbol, timeframe=timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)

        frame = data.copy()
        if frame.index.name != "timestamp":
            frame.index.name = "timestamp"
        frame = frame.reset_index()
        frame.to_parquet(path, index=False)
        return path
