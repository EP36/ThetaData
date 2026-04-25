"""File-based positions ledger for Polymarket open/closed trades.

# SETUP: Add DATABASE_URL to /etc/trauto/env on Hetzner.
# Value: the Render Postgres connection string from Render dashboard
# → trauto-postgres → Connect → External Connection String
# Then run: systemctl restart trauto-worker
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("theta.polymarket.positions")

# ---------------------------------------------------------------------------
# Status state machine
# ---------------------------------------------------------------------------

#: Valid next statuses for each current status. Terminal states map to empty set.
VALID_TRANSITIONS: dict[str, set[str]] = {
    "open":     {"closing", "resolved", "stale"},
    "closing":  {"closed", "closing"},   # "closing" → "closing" allows retry
    "unhedged": {"closing", "closed"},
    "closed":   set(),                   # terminal
    "resolved": set(),                   # terminal
    "stale":    set(),                   # terminal — requires human review
}

#: Statuses that represent an active (not-yet-final) position.
ACTIVE_STATUSES: frozenset[str] = frozenset({"open", "unhedged", "closing"})

#: Statuses that have finalized P&L.
FINAL_STATUSES: frozenset[str] = frozenset({"closed", "resolved"})


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------

@dataclass
class PositionRecord:
    """One side (or both sides) of an entered arb position."""

    # Phase 1+2: required fields
    id: str
    market_condition_id: str
    market_question: str
    strategy: str       # "orderbook_spread" | "cross_market" | "correlated_markets"
    side: str           # "YES" | "NO" | "YES+NO"
    entry_price: float
    size_usdc: float
    opened_at: str      # ISO-8601 UTC
    status: str         # see VALID_TRANSITIONS above
    pnl: float | None = None
    # Phase 3: monitoring fields (all optional — existing JSON records use defaults)
    yes_token_id: str = ""
    no_token_id: str = ""
    end_date: str = ""              # market end date ISO-8601; used for stale detection
    exit_price: float | None = None
    closed_at: str = ""
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    contracts_held: float = 0.0    # outcome tokens held per leg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _today_date() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PositionsLedger:
    """Atomic JSON-file ledger for Polymarket positions.

    All writes use a write-then-rename pattern to avoid partial writes.
    Not safe for concurrent multi-process use (single-process scanner only).
    """

    path: Path

    def _load_raw(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.error("positions_load_error path=%s error=%s", self.path, exc)
            return []

    def _save_raw(self, records: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
            os.replace(tmp, self.path)
        except OSError as exc:
            LOGGER.error("positions_save_error path=%s error=%s", self.path, exc)
            raise

    def load(self) -> list[PositionRecord]:
        """Return all persisted position records."""
        return [PositionRecord(**r) for r in self._load_raw()]

    def open_positions(self) -> list[PositionRecord]:
        """Return positions in any active (non-terminal) state."""
        return [p for p in self.load() if p.status in ACTIVE_STATUSES]

    def add(self, record: PositionRecord) -> None:
        """Append a new position record and persist."""
        raw = self._load_raw()
        raw.append(asdict(record))
        self._save_raw(raw)
        LOGGER.info(
            "positions_add id=%s strategy=%s side=%s size_usdc=%.2f status=%s",
            record.id,
            record.strategy,
            record.side,
            record.size_usdc,
            record.status,
        )

    def update_status(
        self,
        position_id: str,
        status: str,
        pnl: float | None = None,
    ) -> None:
        """Update status and optional P&L for one position record (legacy helper)."""
        extra: dict[str, Any] = {}
        if pnl is not None:
            extra["pnl"] = pnl
        self.update_fields(position_id, status=status, **extra)

    def update_fields(self, position_id: str, **fields: Any) -> None:
        """Update arbitrary fields on one position record without state validation."""
        raw = self._load_raw()
        found = False
        for r in raw:
            if r.get("id") == position_id:
                r.update(fields)
                found = True
                break
        if not found:
            LOGGER.warning("positions_update_not_found id=%s fields=%s", position_id, list(fields))
            return
        self._save_raw(raw)

    def transition(
        self,
        position_id: str,
        new_status: str,
        reason: str,
        **extra_fields: Any,
    ) -> bool:
        """Validate and apply a state transition.

        Logs every transition. Returns False (and logs a warning) if the
        transition is invalid — never silently applies a bad state change.
        """
        raw = self._load_raw()
        target: dict | None = next(
            (r for r in raw if r.get("id") == position_id), None
        )
        if target is None:
            LOGGER.warning("positions_transition_not_found id=%s", position_id)
            return False

        current_status = target.get("status", "")
        valid_next = VALID_TRANSITIONS.get(current_status, set())

        if new_status not in valid_next:
            LOGGER.warning(
                "positions_invalid_transition id=%s from=%s to=%s reason=%s",
                position_id,
                current_status,
                new_status,
                reason,
            )
            return False

        target["status"] = new_status
        target.update(extra_fields)
        self._save_raw(raw)
        LOGGER.info(
            "positions_transition id=%s from=%s to=%s reason=%s",
            position_id,
            current_status,
            new_status,
            reason,
        )
        if new_status in ("closed", "resolved") and target.get("pnl") is not None:
            try:
                closed_record = PositionRecord(**target)
                _persist_fill_to_db(closed_record)
            except Exception as exc:
                LOGGER.warning("positions_fill_persist_error id=%s error=%s", position_id, exc)
        return True

    def record_fill(
        self,
        strategy: str,
        market: str,
        side: str,
        size_usdc: float,
        edge_pct: float,
    ) -> None:
        """Append a lightweight fill record to fills.jsonl for the trades dashboard."""
        fills_path = self.path.parent / "fills.jsonl"
        entry = json.dumps({
            "ts": _now_iso(),
            "strategy": strategy,
            "market": market,
            "side": side,
            "size_usdc": size_usdc,
            "edge_pct": edge_pct,
        })
        try:
            fills_path.parent.mkdir(parents=True, exist_ok=True)
            with fills_path.open("a", encoding="utf-8") as fh:
                fh.write(entry + "\n")
            LOGGER.info(
                "fill_recorded strategy=%s side=%s size_usdc=%.2f edge_pct=%.4f",
                strategy, side, size_usdc, edge_pct,
            )
        except OSError as exc:
            LOGGER.warning("fill_record_error path=%s error=%s", fills_path, exc)

    def open_count(self) -> int:
        """Count active positions (open, unhedged, closing)."""
        return sum(1 for r in self._load_raw() if r.get("status") in ACTIVE_STATUSES)

    def daily_pnl(self) -> float:
        """Sum realized P&L for positions finalized today (UTC).

        Includes both 'closed' and 'resolved' statuses.
        """
        today = _today_date()
        total = 0.0
        for r in self._load_raw():
            if (
                r.get("status") in FINAL_STATUSES
                and r.get("opened_at", "").startswith(today)
            ):
                pnl = r.get("pnl")
                if pnl is not None:
                    total += float(pnl)
        return total


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def make_ledger(positions_path: str) -> PositionsLedger:
    """Construct a PositionsLedger from a file path string."""
    return PositionsLedger(path=Path(positions_path))


def new_position(
    market_condition_id: str,
    market_question: str,
    strategy: str,
    side: str,
    entry_price: float,
    size_usdc: float,
    status: str = "open",
    yes_token_id: str = "",
    no_token_id: str = "",
    end_date: str = "",
    contracts_held: float = 0.0,
) -> PositionRecord:
    """Build a new PositionRecord with a fresh UUID and current timestamp."""
    return PositionRecord(
        id=_new_id(),
        market_condition_id=market_condition_id,
        market_question=market_question,
        strategy=strategy,
        side=side,
        entry_price=entry_price,
        size_usdc=size_usdc,
        opened_at=_now_iso(),
        status=status,
        pnl=None,
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        end_date=end_date,
        contracts_held=contracts_held,
    )


def _persist_fill_to_db(record: PositionRecord) -> None:
    """Write a closed Polymarket position to Postgres poly_fills table.

    Silently no-ops if DATABASE_URL is unset (local dev) or on any error.
    Never raises — DB being unavailable must not crash the scanner.
    """
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url or record.pnl is None:
        return
    if record.size_usdc <= 0:
        return
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=1,
            max_overflow=0,
        )
        pnl_pct = record.pnl / record.size_usdc
        now = datetime.now(tz=timezone.utc)
        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO poly_fills
                      (fill_id, symbol, side, notional, price, pnl, pnl_pct,
                       win, strategy, edge_pct, direction, closed_at, created_at)
                    VALUES
                      (:fill_id, :symbol, :side, :notional, :price, :pnl, :pnl_pct,
                       :win, :strategy, :edge_pct, :direction, :closed_at, :created_at)
                    ON CONFLICT (fill_id) DO NOTHING
                """),
                {
                    "fill_id":    str(uuid.uuid4()),
                    "symbol":     record.market_question[:200],
                    "side":       record.side,
                    "notional":   record.size_usdc,
                    "price":      record.entry_price,
                    "pnl":        record.pnl,
                    "pnl_pct":    pnl_pct,
                    "win":        record.pnl > 0,
                    "strategy":   record.strategy,
                    "edge_pct":   0.0,
                    "direction":  record.side,
                    "closed_at":  now,
                    "created_at": now,
                },
            )
            conn.commit()
        engine.dispose()
        LOGGER.info(
            "poly_fill_persisted symbol=%s pnl=%.4f pnl_pct=%.4f",
            record.market_question[:60],
            record.pnl,
            pnl_pct,
        )
    except Exception as exc:
        LOGGER.warning("poly_fill_persist_error error=%s", exc)
