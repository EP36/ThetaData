"""Database migration/bootstrap entrypoint (create-all for MVP)."""

from __future__ import annotations

import logging

from src.auth.bootstrap_admin import maybe_bootstrap_admin_from_settings
from src.config.deployment import DeploymentSettings
from src.persistence.repository import PersistenceRepository
from src.persistence.store import DatabaseStore

LOGGER = logging.getLogger("theta.persistence.migrate")


def run_migrations() -> None:
    """Create/initialize persistence schema."""
    settings = DeploymentSettings.from_env()
    store = DatabaseStore(database_url=settings.database_url)
    repository = PersistenceRepository(store=store)
    repository.initialize(starting_cash=settings.initial_capital)
    bootstrap_result = maybe_bootstrap_admin_from_settings(
        repository=repository,
        settings=settings,
    )
    if bootstrap_result is not None:
        email, created = bootstrap_result
        LOGGER.info(
            "admin_bootstrap_completed email=%s created=%s",
            email,
            created,
        )
    LOGGER.info("database_schema_ready database_url=%s", settings.database_url)


def main() -> None:
    """CLI wrapper for migration command."""
    run_migrations()


if __name__ == "__main__":
    main()
