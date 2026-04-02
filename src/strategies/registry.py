"""Simple strategy registry for lookup by strategy name."""

from __future__ import annotations

from typing import Type

from src.strategies.base import Strategy

_REGISTRY: dict[str, Type[Strategy]] = {}


def register_strategy(strategy_cls: Type[Strategy]) -> Type[Strategy]:
    """Register a strategy class by its `name`."""
    name = strategy_cls.name.strip()
    if not name:
        raise ValueError("Strategy name cannot be empty")
    if name in _REGISTRY and _REGISTRY[name] is not strategy_cls:
        raise ValueError(f"Strategy '{name}' is already registered")

    _REGISTRY[name] = strategy_cls
    return strategy_cls


def get_strategy_class(name: str) -> Type[Strategy]:
    """Get a registered strategy class by name."""
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"Unknown strategy '{name}'") from exc


def create_strategy(name: str, **kwargs: object) -> Strategy:
    """Instantiate a registered strategy by name."""
    strategy_cls = get_strategy_class(name)
    return strategy_cls(**kwargs)


def list_strategies() -> list[str]:
    """List registered strategy names in sorted order."""
    return sorted(_REGISTRY)


def clear_registry() -> None:
    """Clear registry (primarily for tests)."""
    _REGISTRY.clear()
