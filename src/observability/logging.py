"""Lightweight structured logging utilities with run-scoped context."""

from __future__ import annotations

import contextvars
import logging
from pathlib import Path
from uuid import uuid4

RUN_ID_CONTEXT: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")
_CONFIGURED = False


class RunContextFilter(logging.Filter):
    """Inject run_id from context var into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = RUN_ID_CONTEXT.get()
        return True


def configure_logging(log_dir: str | Path = "logs") -> None:
    """Configure root logging once with console and file handlers."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    output_dir = Path(log_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = output_dir / "system.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [run_id=%(run_id)s] %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_filter = RunContextFilter()

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(run_filter)
    setattr(stream_handler, "_theta_handler", True)

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(run_filter)
    setattr(file_handler, "_theta_handler", True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)

    _CONFIGURED = True


def start_run(run_id: str | None = None) -> str:
    """Set run_id context for all downstream logging in this execution flow."""
    resolved = run_id or uuid4().hex
    RUN_ID_CONTEXT.set(resolved)
    return resolved


def clear_run() -> None:
    """Clear run_id context after a workflow completes."""
    RUN_ID_CONTEXT.set("-")


def current_run_id() -> str:
    """Return current run_id value."""
    return RUN_ID_CONTEXT.get()


def reset_logging_for_tests() -> None:
    """Reset configured handlers for deterministic tests."""
    global _CONFIGURED
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if getattr(handler, "_theta_handler", False):
            root_logger.removeHandler(handler)
            handler.close()
    _CONFIGURED = False
    clear_run()
