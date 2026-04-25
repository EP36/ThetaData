"""In-memory position tracker for open funding arb positions.

Persists to /tmp/funding_arb_positions.json for restart resilience.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

LOGGER = logging.getLogger("theta.funding_arb.positions")
_STATE_FILE = Path("/tmp/funding_arb_positions.json")


@dataclass
class ArbPosition:
    asset: str
    spot_size: float
    perp_size: float
    spot_entry_px: float
    perp_entry_px: float
    size_usd: float
    entry_rate: float
    opened_at: str
    spot_order_id: str
    perp_order_id: str


def load_positions() -> list[ArbPosition]:
    if not _STATE_FILE.exists():
        return []
    try:
        data = json.loads(_STATE_FILE.read_text())
        return [ArbPosition(**p) for p in data]
    except Exception as exc:
        LOGGER.warning("positions_load_error error=%s", exc)
        return []


def save_positions(positions: list[ArbPosition]) -> None:
    try:
        _STATE_FILE.write_text(json.dumps([asdict(p) for p in positions], indent=2))
    except Exception as exc:
        LOGGER.warning("positions_save_error error=%s", exc)


def add_position(pos: ArbPosition) -> None:
    positions = load_positions()
    positions.append(pos)
    save_positions(positions)
    LOGGER.info(
        "arb_position_opened asset=%s size_usd=%.2f entry_rate=%.4f%%",
        pos.asset, pos.size_usd, pos.entry_rate * 100,
    )


def remove_position(asset: str) -> ArbPosition | None:
    positions = load_positions()
    removed = next((p for p in positions if p.asset == asset), None)
    if removed:
        save_positions([p for p in positions if p.asset != asset])
        LOGGER.info("arb_position_closed asset=%s", asset)
    return removed
