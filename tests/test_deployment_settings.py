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


def test_strict_mode_requires_explicit_required_env_vars(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("")

    for env_name in (
        "APP_ENV",
        "DATABASE_URL",
        "WORKER_NAME",
        "PAPER_TRADING",
        "WORKER_ENABLE_TRADING",
        "LIVE_TRADING",
    ):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "true")

    with pytest.raises(ValueError, match="Missing required environment variables"):
        DeploymentSettings.from_env(env_path=empty_env)


def test_production_mode_missing_database_url_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("")

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WORKER_NAME", "main-worker")
    monkeypatch.setenv("PAPER_TRADING", "false")
    monkeypatch.setenv("WORKER_ENABLE_TRADING", "false")
    monkeypatch.setenv("LIVE_TRADING", "false")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="DATABASE_URL"):
        DeploymentSettings.from_env(env_path=empty_env)
