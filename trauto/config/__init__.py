"""Unified configuration system.

Load order: default.json → config/local.json → environment variables (wins).

Usage:
    from trauto.config import config
    config.get("engine.tick_ms")          # → 100
    config.get("risk.global_max_positions") # → 20

Dot-notation keys traverse the nested JSON structure.
Environment variables use the same dot path converted to uppercase with
dots replaced by underscores: engine.tick_ms → ENGINE_TICK_MS.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("trauto.config")

_DEFAULT_PATH = Path(__file__).parent / "default.json"
_LOCAL_PATH = Path(__file__).parent / "local.json"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _coerce(value: str, existing: Any) -> Any:
    """Coerce an env-var string to the same type as the existing default."""
    if isinstance(existing, bool):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(existing, int):
        try:
            return int(value)
        except ValueError:
            return float(value)
    if isinstance(existing, float):
        return float(value)
    if isinstance(existing, list):
        return [v.strip() for v in value.split(",") if v.strip()]
    return value


class TConfig:
    """Layered configuration: defaults → local.json → env vars."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        """Reload all config layers from disk."""
        data: dict[str, Any] = {}

        # Layer 1: defaults
        try:
            data = json.loads(_DEFAULT_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            LOGGER.error("config_default_load_failed error=%s", exc)

        # Layer 2: local.json overrides
        if _LOCAL_PATH.exists():
            try:
                local = json.loads(_LOCAL_PATH.read_text(encoding="utf-8"))
                data = _deep_merge(data, local)
                LOGGER.debug("config_local_loaded path=%s", _LOCAL_PATH)
            except Exception as exc:
                LOGGER.warning("config_local_load_failed path=%s error=%s", _LOCAL_PATH, exc)

        # Layer 3: environment variables (uppercase dot-to-underscore)
        self._apply_env(data)
        self._data = data

    def _apply_env(self, data: dict, prefix: str = "") -> None:
        """Walk the config tree and apply matching env-var overrides in-place."""
        for key, val in data.items():
            path = f"{prefix}.{key}" if prefix else key
            env_key = path.upper().replace(".", "_")
            raw = os.getenv(env_key)
            if raw is not None:
                data[key] = _coerce(raw, val)
                LOGGER.debug("config_env_override key=%s env=%s", path, env_key)
            elif isinstance(val, dict):
                self._apply_env(val, path)

    def get(self, key: str, default: Any = None) -> Any:
        """Return config value by dot-notation key, or default."""
        parts = key.split(".")
        node: Any = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any) -> None:
        """Set a config value at runtime (does not persist to disk)."""
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value

    def as_dict(self) -> dict[str, Any]:
        """Return a deep copy of the full config tree."""
        return json.loads(json.dumps(self._data))


# Module-level singleton — import and use directly
config = TConfig()
