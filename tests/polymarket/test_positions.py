"""Tests for PositionsLedger — save/load round-trip, counts, daily P&L."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.polymarket.positions import (
    PositionRecord,
    PositionsLedger,
    new_position,
)


def _ledger(tmp_path: Path) -> PositionsLedger:
    return PositionsLedger(path=tmp_path / "positions.json")


def _open_pos(**overrides) -> PositionRecord:
    defaults = dict(
        market_condition_id="0xabc",
        market_question="Will BTC hit $100k?",
        strategy="orderbook_spread",
        side="YES+NO",
        entry_price=0.82,
        size_usdc=200.0,
        status="open",
    )
    defaults.update(overrides)
    return new_position(**defaults)


def test_ledger_load_returns_empty_when_file_missing(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    assert ledger.load() == []


def test_ledger_add_and_load_roundtrip(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    pos = _open_pos()

    ledger.add(pos)
    loaded = ledger.load()

    assert len(loaded) == 1
    assert loaded[0].id == pos.id
    assert loaded[0].market_condition_id == "0xabc"
    assert loaded[0].strategy == "orderbook_spread"
    assert loaded[0].side == "YES+NO"
    assert loaded[0].entry_price == pytest.approx(0.82)
    assert loaded[0].size_usdc == pytest.approx(200.0)
    assert loaded[0].status == "open"
    assert loaded[0].pnl is None


def test_ledger_add_multiple_positions(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.add(_open_pos())
    ledger.add(_open_pos())
    assert len(ledger.load()) == 2


def test_ledger_update_status_to_closed(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    pos = _open_pos()
    ledger.add(pos)

    ledger.update_status(pos.id, status="closed", pnl=15.50)

    loaded = ledger.load()
    assert loaded[0].status == "closed"
    assert loaded[0].pnl == pytest.approx(15.50)


def test_ledger_update_status_to_unhedged(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    pos = _open_pos()
    ledger.add(pos)

    ledger.update_status(pos.id, status="unhedged")

    assert ledger.load()[0].status == "unhedged"


def test_ledger_update_unknown_id_is_a_noop(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    pos = _open_pos()
    ledger.add(pos)

    ledger.update_status("nonexistent-uuid", status="closed", pnl=0.0)

    assert ledger.load()[0].status == "open"


def test_open_count_counts_open_and_unhedged(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.add(_open_pos(status="open"))
    ledger.add(_open_pos(status="open"))
    closed = _open_pos()
    ledger.add(closed)
    ledger.update_status(closed.id, "closed", pnl=10.0)

    assert ledger.open_count() == 2


def test_open_count_includes_unhedged(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.add(_open_pos(status="unhedged"))
    assert ledger.open_count() == 1


def test_open_count_zero_when_all_closed(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    p1 = _open_pos()
    ledger.add(p1)
    ledger.update_status(p1.id, "closed", pnl=5.0)
    assert ledger.open_count() == 0


def test_daily_pnl_sums_closed_positions(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    p1 = _open_pos()
    p2 = _open_pos()
    ledger.add(p1)
    ledger.add(p2)
    ledger.update_status(p1.id, "closed", pnl=10.0)
    ledger.update_status(p2.id, "closed", pnl=-5.0)

    assert ledger.daily_pnl() == pytest.approx(5.0)


def test_daily_pnl_zero_when_no_closed_positions(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.add(_open_pos(status="open"))
    assert ledger.daily_pnl() == pytest.approx(0.0)


def test_ledger_write_is_atomic_via_tmp_rename(tmp_path: Path) -> None:
    """Verify a .tmp file is never left behind after a successful write."""
    ledger = _ledger(tmp_path)
    ledger.add(_open_pos())
    tmp_file = ledger.path.with_suffix(".tmp")
    assert not tmp_file.exists()


def test_new_position_generates_unique_ids(tmp_path: Path) -> None:
    p1 = _open_pos()
    p2 = _open_pos()
    assert p1.id != p2.id


def test_new_position_has_iso_timestamp(tmp_path: Path) -> None:
    pos = _open_pos()
    assert "T" in pos.opened_at  # ISO-8601 has a T separator
    assert pos.opened_at.endswith("+00:00") or pos.opened_at.endswith("Z")
