"""Tests for the unified config system."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from trauto.config import TConfig, _deep_merge


class TestDeepMerge:
    def test_simple_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        assert _deep_merge(base, override) == {"a": 1, "b": 99}

    def test_nested_merge(self):
        base = {"engine": {"tick_ms": 100, "dry_run": True}}
        override = {"engine": {"dry_run": False}}
        result = _deep_merge(base, override)
        assert result["engine"]["tick_ms"] == 100
        assert result["engine"]["dry_run"] is False

    def test_deep_nested(self):
        base = {"a": {"b": {"c": 1, "d": 2}}}
        override = {"a": {"b": {"d": 99}}}
        result = _deep_merge(base, override)
        assert result["a"]["b"]["c"] == 1
        assert result["a"]["b"]["d"] == 99

    def test_does_not_mutate_base(self):
        base = {"a": 1}
        override = {"a": 2}
        _deep_merge(base, override)
        assert base["a"] == 1


class TestTConfig:
    def test_defaults_loaded(self):
        cfg = TConfig()
        assert cfg.get("engine.tick_ms") == 100
        assert cfg.get("engine.dry_run") is True
        assert cfg.get("risk.global_max_positions") == 20

    def test_get_nested(self):
        cfg = TConfig()
        assert cfg.get("polymarket.dry_run") is True

    def test_get_missing_returns_default(self):
        cfg = TConfig()
        assert cfg.get("nonexistent.key") is None
        assert cfg.get("nonexistent.key", "fallback") == "fallback"

    def test_set_runtime(self):
        cfg = TConfig()
        cfg.set("engine.tick_ms", 200)
        assert cfg.get("engine.tick_ms") == 200

    def test_env_var_override_int(self, monkeypatch):
        monkeypatch.setenv("ENGINE_TICK_MS", "250")
        cfg = TConfig()
        assert cfg.get("engine.tick_ms") == 250

    def test_env_var_override_bool_true(self, monkeypatch):
        monkeypatch.setenv("ENGINE_DRY_RUN", "false")
        cfg = TConfig()
        assert cfg.get("engine.dry_run") is False

    def test_env_var_override_float(self, monkeypatch):
        monkeypatch.setenv("RISK_GLOBAL_DAILY_LOSS_LIMIT", "1500.5")
        cfg = TConfig()
        assert cfg.get("risk.global_daily_loss_limit") == 1500.5

    def test_as_dict_returns_copy(self):
        cfg = TConfig()
        d = cfg.as_dict()
        d["engine"]["tick_ms"] = 9999
        assert cfg.get("engine.tick_ms") == 100  # unchanged

    def test_local_json_override(self, tmp_path, monkeypatch):
        """Test that local.json values override defaults."""
        local_path = tmp_path / "local.json"
        local_path.write_text(json.dumps({"engine": {"tick_ms": 999}}), encoding="utf-8")
        # Monkeypath the _LOCAL_PATH
        import trauto.config as cfg_module
        monkeypatch.setattr(cfg_module, "_LOCAL_PATH", local_path)
        cfg = TConfig()
        assert cfg.get("engine.tick_ms") == 999

    def test_env_wins_over_local(self, tmp_path, monkeypatch):
        local_path = tmp_path / "local.json"
        local_path.write_text(json.dumps({"engine": {"tick_ms": 500}}), encoding="utf-8")
        import trauto.config as cfg_module
        monkeypatch.setattr(cfg_module, "_LOCAL_PATH", local_path)
        monkeypatch.setenv("ENGINE_TICK_MS", "777")
        cfg = TConfig()
        assert cfg.get("engine.tick_ms") == 777
