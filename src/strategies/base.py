"""Base strategy interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

import pandas as pd


@dataclass(frozen=True, slots=True)
class StrategyMetadata:
    """Describes a strategy's identity and required inputs."""

    name: str
    required_columns: tuple[str, ...]


class Strategy(ABC):
    """Abstract strategy interface for pluggable signal generation."""

    name: ClassVar[str] = "base_strategy"
    required_columns: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def metadata(cls) -> StrategyMetadata:
        """Return strategy metadata for registry/reporting use."""
        return StrategyMetadata(name=cls.name, required_columns=cls.required_columns)

    @classmethod
    def validate_required_columns(cls, data: pd.DataFrame) -> None:
        """Validate required data columns for this strategy."""
        missing = [column for column in cls.required_columns if column not in data.columns]
        if missing:
            raise ValueError(
                f"Strategy '{cls.name}' missing required columns: {missing}"
            )

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """Return strategy signals aligned with market data index.

        Signal convention:
            DataFrame containing a `signal` column with target exposure values.

        Args:
            data: Market data DataFrame.

        Returns:
            Signal DataFrame indexed like `data`.
        """
        raise NotImplementedError
