"""Atomic runner heartbeat writer.

Called by run_strategies.py after each tick to write
logs/theta_runner_status.json.  The API server reads this file to
distinguish live runner state from historical trade telemetry.

Design:
  - Writes to a temp file then os.replace() so readers never see a partial file.
  - Never raises — a failed write is logged and silently swallowed so the
    runner loop is not disrupted.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger("theta.orchestration.status_writer")

STATUS_FILENAME = "theta_runner_status.json"

# A heartbeat older than this many seconds is considered stale by the API.
# Must exceed the longest expected sleep interval between runner ticks.
STALE_THRESHOLD_SECONDS: int = 300


def write_runner_status(
    log_dir: str | Path,
    *,
    mode: str,
    strategies_evaluated: list[str],
    iterations_completed: int,
    selected_strategy: Optional[str],
    last_result: str,
    last_error: Optional[str],
) -> None:
    """Write a heartbeat JSON file atomically.

    Args:
        log_dir:               Directory to write into (created if absent).
        mode:                  "dry_run" or "live".
        strategies_evaluated:  Names of all strategies that ran evaluate().
        iterations_completed:  Total loop iterations finished so far.
        selected_strategy:     Name of the strategy selected for execution, or None.
        last_result:           Short outcome label, e.g. "no_opportunity",
                               "dry_run_would_execute", "executed", "failed",
                               "blocked_by_risk".
        last_error:            Error message from the most recent failure, or None.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    payload: dict = {
        "runner_alive": True,
        "last_tick_at": now_iso,
        "mode": mode,
        "strategies_evaluated": strategies_evaluated,
        "iterations_completed": iterations_completed,
        "selected_strategy": selected_strategy,
        "last_result": last_result,
        "last_error": last_error,
        "written_at": now_iso,
    }
    dest = Path(log_dir) / STATUS_FILENAME
    try:
        _atomic_write(dest, payload)
    except Exception as exc:
        LOGGER.warning("runner_status_write_failed path=%s error=%s", dest, exc)


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_runner_status_")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
