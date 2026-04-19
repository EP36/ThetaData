"""File-based positions ledger for Polymarket open/closed trades."""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger("theta.polymarket.positions")


@dataclass
class PositionRecord:
    """One side (or both sides) of an entered arb position."""

    id: str
    market_condition_id: str
    market_question: str
    strategy: str          # "orderbook_spread" | "cross_market" | "correlated_markets"
    side: str              # "YES" | "NO" | "YES+NO"
    entry_price: float
    size_usdc: float
    opened_at: str         # ISO-8601 UTC timestamp
    status: str            # "open" | "closed" | "unhedged"
    pnl: float | None = None


def _new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _today_date() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


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
        """Update status and optional P&L for one position record."""
        raw = self._load_raw()
        found = False
        for r in raw:
            if r.get("id") == position_id:
                r["status"] = status
                if pnl is not None:
                    r["pnl"] = pnl
                found = True
                break
        if not found:
            LOGGER.warning("positions_update_not_found id=%s", position_id)
            return
        self._save_raw(raw)
        LOGGER.info(
            "positions_update id=%s status=%s pnl=%s",
            position_id,
            status,
            pnl,
        )

    def open_count(self) -> int:
        """Return the number of currently open (or unhedged) positions."""
        return sum(
            1 for r in self._load_raw() if r.get("status") in {"open", "unhedged"}
        )

    def daily_pnl(self) -> float:
        """Sum realized P&L for positions closed today (UTC)."""
        today = _today_date()
        total = 0.0
        for r in self._load_raw():
            if r.get("status") == "closed" and r.get("opened_at", "").startswith(today):
                pnl = r.get("pnl")
                if pnl is not None:
                    total += float(pnl)
        return total


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
    )
