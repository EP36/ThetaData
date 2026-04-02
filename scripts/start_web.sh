#!/usr/bin/env bash
set -euo pipefail

if [[ "${RUN_MIGRATIONS_ON_STARTUP:-true}" == "true" ]]; then
  python -m src.persistence.migrate
fi

exec python -m src.api
