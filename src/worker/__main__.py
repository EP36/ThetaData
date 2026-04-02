"""Run the background trading worker process."""

from __future__ import annotations

from src.config.deployment import DeploymentSettings
from src.persistence import DatabaseStore, PersistenceRepository
from src.worker.service import TradingWorker


def main() -> None:
    """Bootstrap and run worker forever."""
    settings = DeploymentSettings.from_env()
    repository = PersistenceRepository(
        store=DatabaseStore(database_url=settings.database_url)
    )
    worker = TradingWorker(settings=settings, repository=repository)
    worker.run_forever()


if __name__ == "__main__":
    main()
