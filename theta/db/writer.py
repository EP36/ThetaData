"""Theta DB writer: write runner status and trade records to Postgres.

Used by the theta-runner on Hetzner to push telemetry into the shared
Render Postgres database so the web dashboard on Render can read it.

Reads DATABASE_URL from the environment.  If the variable is unset
(e.g., local dev without a DB), all writes are silently skipped — the
local JSONL / JSON files remain the only telemetry channel.

SQLAlchemy Core (text + engine) is used instead of the ORM to keep the
theta package self-contained.  The same tables are declared as ORM models
in src/persistence/models.py so that the API side can rely on
DatabaseStore.create_schema() to bootstrap the tables on Render startup.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from theta.telemetry.trade_log import TradeRecord

LOGGER = logging.getLogger("theta.db.writer")

_engine = None  # module-level cached engine

# ---------------------------------------------------------------------------
# DDL — tables created by the runner at startup (IF NOT EXISTS is idempotent)
# ---------------------------------------------------------------------------

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS theta_runner_status (
        runner_key           VARCHAR(100) PRIMARY KEY,
        mode                 VARCHAR(20)  NOT NULL DEFAULT 'dry_run',
        last_tick_at         TIMESTAMPTZ,
        last_result          VARCHAR(50),
        last_error           TEXT,
        iterations_completed INTEGER      NOT NULL DEFAULT 0,
        selected_strategy    VARCHAR(100),
        strategies_evaluated TEXT         NOT NULL DEFAULT '[]',
        written_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS theta_trades (
        id                  BIGSERIAL    PRIMARY KEY,
        runner_key          VARCHAR(100) NOT NULL DEFAULT 'default',
        trade_timestamp     TIMESTAMPTZ  NOT NULL,
        strategy            VARCHAR(100) NOT NULL,
        exchange            VARCHAR(50)  NOT NULL,
        asset               VARCHAR(20)  NOT NULL,
        quote               VARCHAR(20)  NOT NULL DEFAULT 'USD',
        side                VARCHAR(10)  NOT NULL,
        notional_usd        DOUBLE PRECISION NOT NULL DEFAULT 0,
        expected_edge_bps   DOUBLE PRECISION NOT NULL DEFAULT 0,
        mid_price_at_order  DOUBLE PRECISION NOT NULL DEFAULT 0,
        order_id            VARCHAR(200) NOT NULL DEFAULT '',
        client_order_id     VARCHAR(200) NOT NULL DEFAULT '',
        status              VARCHAR(30)  NOT NULL,
        error               TEXT,
        dry_run             BOOLEAN      NOT NULL DEFAULT FALSE,
        created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_theta_trades_ts       ON theta_trades (trade_timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS ix_theta_trades_strategy ON theta_trades (strategy, trade_timestamp DESC)",
]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _get_engine():
    """Return a cached SQLAlchemy engine, or None when DATABASE_URL is absent."""
    global _engine
    if _engine is not None:
        return _engine
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        LOGGER.debug("DATABASE_URL not set — theta DB writes disabled")
        return None
    try:
        from sqlalchemy import create_engine
        _engine = create_engine(
            db_url,
            future=True,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=3,
        )
        LOGGER.info("theta_db_engine_ready db_url_prefix=%s", db_url[:30])
    except Exception as exc:
        LOGGER.warning("theta_db_connect_failed error=%s", exc)
    return _engine


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

def ensure_schema() -> None:
    """Create theta tables if they do not already exist.

    Called once at runner startup.  Safe to call multiple times.
    """
    engine = _get_engine()
    if engine is None:
        return
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            for stmt in _DDL:
                conn.execute(text(stmt))
        LOGGER.info("theta_db_schema_ready")
    except Exception as exc:
        LOGGER.warning("theta_db_ensure_schema_failed error=%s", exc)


# ---------------------------------------------------------------------------
# Runner status upsert
# ---------------------------------------------------------------------------

def write_runner_status(
    runner_key: str,
    mode: str,
    last_tick_at: datetime,
    last_result: str,
    last_error: Optional[str],
    iterations_completed: int,
    selected_strategy: Optional[str],
    strategies_evaluated: list[str],
) -> None:
    """Upsert a runner heartbeat row in theta_runner_status."""
    engine = _get_engine()
    if engine is None:
        return
    try:
        from sqlalchemy import text
        sql = text("""
            INSERT INTO theta_runner_status
                (runner_key, mode, last_tick_at, last_result, last_error,
                 iterations_completed, selected_strategy, strategies_evaluated, written_at)
            VALUES
                (:runner_key, :mode, :last_tick_at, :last_result, :last_error,
                 :iterations_completed, :selected_strategy, :strategies_evaluated, :written_at)
            ON CONFLICT (runner_key) DO UPDATE SET
                mode                 = EXCLUDED.mode,
                last_tick_at         = EXCLUDED.last_tick_at,
                last_result          = EXCLUDED.last_result,
                last_error           = EXCLUDED.last_error,
                iterations_completed = EXCLUDED.iterations_completed,
                selected_strategy    = EXCLUDED.selected_strategy,
                strategies_evaluated = EXCLUDED.strategies_evaluated,
                written_at           = EXCLUDED.written_at
        """)
        with engine.begin() as conn:
            conn.execute(sql, {
                "runner_key": runner_key,
                "mode": mode,
                "last_tick_at": last_tick_at,
                "last_result": last_result,
                "last_error": last_error,
                "iterations_completed": iterations_completed,
                "selected_strategy": selected_strategy,
                "strategies_evaluated": json.dumps(strategies_evaluated),
                "written_at": datetime.now(timezone.utc),
            })
        LOGGER.info("status_write_db runner_key=%s result=%s", runner_key, last_result)
    except Exception as exc:
        LOGGER.warning("status_write_db_failed runner_key=%s error=%s", runner_key, exc)


# ---------------------------------------------------------------------------
# Trade insert
# ---------------------------------------------------------------------------

def write_trade(
    record: "TradeRecord",
    strategy_name: str,
    runner_key: Optional[str] = None,
) -> None:
    """Insert a trade record into theta_trades.

    Args:
        record:        TradeRecord from theta.telemetry.trade_log.
        strategy_name: e.g. "coinbase_spot_eth_usd"
        runner_key:    Identifies the runner instance; reads THETA_RUNNER_KEY
                       env var with default "default".
    """
    engine = _get_engine()
    if engine is None:
        return
    key = runner_key or os.getenv("THETA_RUNNER_KEY", "default")
    try:
        from sqlalchemy import text
        ts_str = getattr(record, "timestamp", None)
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                ts = datetime.now(timezone.utc)
        else:
            ts = datetime.now(timezone.utc)

        sql = text("""
            INSERT INTO theta_trades
                (runner_key, trade_timestamp, strategy, exchange, asset, quote,
                 side, notional_usd, expected_edge_bps, mid_price_at_order,
                 order_id, client_order_id, status, error, dry_run)
            VALUES
                (:runner_key, :trade_timestamp, :strategy, :exchange, :asset, :quote,
                 :side, :notional_usd, :expected_edge_bps, :mid_price_at_order,
                 :order_id, :client_order_id, :status, :error, :dry_run)
        """)
        with engine.begin() as conn:
            conn.execute(sql, {
                "runner_key": key,
                "trade_timestamp": ts,
                "strategy": strategy_name,
                "exchange": record.exchange,
                "asset": record.asset,
                "quote": record.quote,
                "side": record.side,
                "notional_usd": float(record.notional_usd),
                "expected_edge_bps": float(record.expected_edge_bps),
                "mid_price_at_order": float(record.mid_price_at_order),
                "order_id": record.order_id or "",
                "client_order_id": record.client_order_id or "",
                "status": record.status,
                "error": record.error or None,
                "dry_run": record.status == "dry_run",
            })
        LOGGER.info(
            "trade_write_db strategy=%s side=%s notional=%.2f status=%s",
            strategy_name, record.side, record.notional_usd, record.status,
        )
    except Exception as exc:
        LOGGER.warning("trade_write_db_failed strategy=%s error=%s", strategy_name, exc)
