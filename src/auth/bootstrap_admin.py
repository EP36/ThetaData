"""Bootstrap helpers and CLI for initial admin-user provisioning."""

from __future__ import annotations

import argparse

from src.auth.service import AuthService
from src.config.deployment import DeploymentSettings
from src.persistence import DatabaseStore, PersistenceRepository


def maybe_bootstrap_admin_from_settings(
    repository: PersistenceRepository,
    settings: DeploymentSettings,
) -> tuple[str, bool] | None:
    """Create/update bootstrap admin when env-controlled startup bootstrap is enabled."""
    if not settings.auth_enabled:
        return None
    if not settings.auth_bootstrap_admin_on_startup:
        return None

    email = settings.auth_bootstrap_admin_email.strip().lower()
    password = settings.auth_bootstrap_admin_password
    if not email or not password:
        raise ValueError(
            "AUTH_BOOTSTRAP_ADMIN_ON_STARTUP=true requires "
            "AUTH_BOOTSTRAP_ADMIN_EMAIL and AUTH_BOOTSTRAP_ADMIN_PASSWORD"
        )

    auth_service = AuthService(repository=repository, settings=settings)
    user, created = auth_service.bootstrap_admin(email=email, password=password)
    return user.email, created


def bootstrap_admin_via_cli(email: str, password: str) -> tuple[str, bool]:
    """CLI entrypoint helper for admin bootstrap."""
    settings = DeploymentSettings.from_env()
    store = DatabaseStore(database_url=settings.database_url)
    repository = PersistenceRepository(store=store)
    repository.initialize(starting_cash=settings.initial_capital)

    auth_service = AuthService(repository=repository, settings=settings)
    user, created = auth_service.bootstrap_admin(email=email, password=password)
    return user.email, created


def parse_args() -> argparse.Namespace:
    """Parse bootstrap CLI arguments."""
    parser = argparse.ArgumentParser(description="Create or update the initial admin user")
    parser.add_argument("--email", required=True, help="Admin email/username")
    parser.add_argument(
        "--password",
        required=True,
        help="Admin password (minimum 12 characters)",
    )
    return parser.parse_args()


def main() -> None:
    """Run bootstrap command."""
    args = parse_args()
    email, created = bootstrap_admin_via_cli(email=args.email, password=args.password)
    status = "created" if created else "updated"
    print(f"admin_user_{status} email={email}")


if __name__ == "__main__":
    main()
