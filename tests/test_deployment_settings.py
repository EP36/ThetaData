"""Tests for deployment/runtime environment validation."""

from __future__ import annotations

import pytest

from src.config.deployment import DeploymentSettings


def test_defaults_keep_trading_disabled() -> None:
    settings = DeploymentSettings()
    assert settings.paper_trading_enabled is False
    assert settings.worker_enable_trading is False


def test_worker_trading_requires_paper_mode() -> None:
    with pytest.raises(ValueError, match="worker_enable_trading requires"):
        DeploymentSettings(worker_enable_trading=True, paper_trading_enabled=False)


def test_production_requires_postgres_database() -> None:
    with pytest.raises(ValueError, match="requires a Postgres DATABASE_URL"):
        DeploymentSettings(app_env="production", database_url="sqlite+pysqlite:///data/theta.db")


def test_from_env_normalizes_render_postgres_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://example.com:5432/theta")
    settings = DeploymentSettings.from_env()
    assert settings.database_url.startswith("postgresql+psycopg://")
