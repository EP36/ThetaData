"""Run API app with uvicorn."""

from __future__ import annotations

import uvicorn

from src.config.deployment import DeploymentSettings


def main() -> None:
    """Run API server using deployment-aware host/port settings."""
    settings = DeploymentSettings.from_env()
    uvicorn.run(
        "src.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
