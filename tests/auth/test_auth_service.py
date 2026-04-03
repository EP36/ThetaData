"""Tests for auth service behavior and security gates."""

from __future__ import annotations

import pytest

from src.auth.security import hash_password
from src.auth.service import (
    AuthService,
    AuthenticationError,
    AuthorizationError,
    LoginRateLimitError,
)
from src.config.deployment import DeploymentSettings
from src.persistence import DatabaseStore, PersistenceRepository


def _settings(database_url: str, **overrides: object) -> DeploymentSettings:
    base = {
        "app_env": "development",
        "database_url": database_url,
        "auth_session_secret": "s" * 40,
        "auth_password_pepper": "p" * 40,
    }
    base.update(overrides)
    return DeploymentSettings(**base)


def test_bootstrap_login_logout_flow(tmp_path) -> None:
    db_path = tmp_path / "theta-auth.db"
    database_url = f"sqlite+pysqlite:///{db_path}"
    repository = PersistenceRepository(store=DatabaseStore(database_url=database_url))
    settings = _settings(database_url=database_url)
    repository.initialize(starting_cash=100_000.0)
    service = AuthService(repository=repository, settings=settings)

    user, created = service.bootstrap_admin(email="admin@example.com", password="ChangeMeNow123!")
    assert created is True
    assert user.role == "admin"

    login = service.login(
        email="admin@example.com",
        password="ChangeMeNow123!",
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    assert login.token
    assert login.user.email == "admin@example.com"

    authenticated_user, _ = service.authenticate_token(login.token)
    assert authenticated_user.email == "admin@example.com"

    service.logout(login.token)
    with pytest.raises(AuthenticationError):
        service.authenticate_token(login.token)


def test_login_rate_limit_blocks_after_threshold(tmp_path) -> None:
    db_path = tmp_path / "theta-auth.db"
    database_url = f"sqlite+pysqlite:///{db_path}"
    repository = PersistenceRepository(store=DatabaseStore(database_url=database_url))
    settings = _settings(
        database_url=database_url,
        auth_login_max_attempts=2,
        auth_login_window_seconds=300,
        auth_login_block_seconds=300,
    )
    repository.initialize(starting_cash=100_000.0)
    service = AuthService(repository=repository, settings=settings)
    service.bootstrap_admin(email="admin@example.com", password="ChangeMeNow123!")

    with pytest.raises(AuthenticationError):
        service.login(
            email="admin@example.com",
            password="bad-password",
            ip_address="127.0.0.1",
            user_agent="pytest",
        )

    with pytest.raises(AuthenticationError):
        service.login(
            email="admin@example.com",
            password="bad-password",
            ip_address="127.0.0.1",
            user_agent="pytest",
        )

    with pytest.raises(LoginRateLimitError):
        service.login(
            email="admin@example.com",
            password="ChangeMeNow123!",
            ip_address="127.0.0.1",
            user_agent="pytest",
        )


def test_require_admin_rejects_non_admin_role(tmp_path) -> None:
    db_path = tmp_path / "theta-auth.db"
    database_url = f"sqlite+pysqlite:///{db_path}"
    repository = PersistenceRepository(store=DatabaseStore(database_url=database_url))
    settings = _settings(database_url=database_url)
    repository.initialize(starting_cash=100_000.0)

    viewer_hash = hash_password(password="ViewerPass123!", pepper=settings.auth_password_pepper)
    repository.create_user(
        email="viewer@example.com",
        password_hash=viewer_hash,
        role="viewer",
        is_active=True,
    )

    service = AuthService(repository=repository, settings=settings)
    login = service.login(
        email="viewer@example.com",
        password="ViewerPass123!",
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    with pytest.raises(AuthorizationError):
        service.require_admin(login.user)
