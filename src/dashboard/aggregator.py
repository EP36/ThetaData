"""Unified data aggregator for the Trauto dashboard.

Pulls live data from both the Alpaca paper trading engine (via
PersistenceRepository) and the Polymarket CLOB scanner (via
PositionsLedger) and returns one normalized snapshot dict.

Falls back to the last cached snapshot per-broker when either source
fails, so the dashboard never crashes due to a single broker error.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.polymarket.alpaca_signals import get_cached_signals
from src.polymarket.config import PolymarketConfig
from src.polymarket.positions import (
    ACTIVE_STATUSES,
    PositionRecord,
    PositionsLedger,
    _today_date,
)

LOGGER = logging.getLogger("theta.dashboard.aggregator")

# File-based pause flag shared between the dashboard API process and the
# scanner process.  dashboard writes it; scanner __main__.py reads it.
POLY_PAUSE_FLAG = Path("data/poly_paused.flag")

_SNAPSHOT_TTL_SEC = 30.0


# ---------------------------------------------------------------------------
# Pause / resume helpers
# ---------------------------------------------------------------------------

def is_poly_paused() -> bool:
    """Return True when the Polymarket scanner has been soft-paused."""
    return POLY_PAUSE_FLAG.exists()


def pause_poly_bot() -> None:
    """Create the pause flag file — scanner will skip execution on next cycle."""
    POLY_PAUSE_FLAG.parent.mkdir(parents=True, exist_ok=True)
    POLY_PAUSE_FLAG.touch()
    LOGGER.warning("dashboard_poly_bot_paused")


def resume_poly_bot() -> None:
    """Remove the pause flag file — scanner resumes normal execution."""
    POLY_PAUSE_FLAG.unlink(missing_ok=True)
    LOGGER.info("dashboard_poly_bot_resumed")


def poly_bot_status(config: PolymarketConfig) -> str:
    """Return 'paused' | 'dry_run' | 'live'."""
    if is_poly_paused():
        return "paused"
    return "dry_run" if config.dry_run else "live"


# ---------------------------------------------------------------------------
# Position normalisation
# ---------------------------------------------------------------------------

def normalize_poly_position(pos: PositionRecord) -> dict[str, Any]:
    """Map a PositionRecord to the common position schema."""
    current = pos.exit_price if pos.exit_price is not None else pos.entry_price
    return {
        "id": pos.id,
        "broker": "polymarket",
        "symbol_or_market": pos.market_question,
        "side": pos.side,
        "entry_price": pos.entry_price,
        "current_price": current,
        "size": pos.contracts_held,
        "size_usd": pos.size_usdc,
        "unrealized_pnl": pos.unrealized_pnl or 0.0,
        "unrealized_pnl_pct": pos.unrealized_pnl_pct or 0.0,
        "opened_at": pos.opened_at,
        "status": pos.status,
        "broker_url": f"https://polymarket.com/event/{pos.market_condition_id}",
    }


def normalize_alpaca_position(pos: Any) -> dict[str, Any]:
    """Map a src.execution.models.Position to the common position schema."""
    qty = float(pos.quantity)
    avg = float(pos.avg_price)
    unrealized = float(pos.unrealized_pnl)
    size_usd = qty * avg
    pct = (unrealized / size_usd * 100.0) if size_usd > 0 else 0.0
    current_price = (size_usd + unrealized) / qty if qty > 0 else avg
    return {
        "id": f"alpaca_{pos.symbol}",
        "broker": "alpaca",
        "symbol_or_market": pos.symbol,
        "side": "long" if qty >= 0 else "short",
        "entry_price": avg,
        "current_price": round(current_price, 4),
        "size": qty,
        "size_usd": round(size_usd, 2),
        "unrealized_pnl": round(unrealized, 2),
        "unrealized_pnl_pct": round(pct, 4),
        "opened_at": "",
        "status": "open",
        "broker_url": "https://app.alpaca.markets",
    }


# ---------------------------------------------------------------------------
# Alert generation
# ---------------------------------------------------------------------------

def _build_alerts(
    poly_positions: list[PositionRecord],
    poly_config: PolymarketConfig,
    alpaca_kill_switch: bool,
    poly_realized_today: float,
    alpaca_error: str | None,
    poly_error: str | None,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []

    if alpaca_kill_switch:
        alerts.append({
            "level": "error",
            "source": "alpaca",
            "message": "Alpaca kill switch is enabled — no orders will execute",
        })

    if is_poly_paused():
        alerts.append({
            "level": "warning",
            "source": "polymarket",
            "message": "Polymarket bot is paused",
        })

    for pos in poly_positions:
        if pos.status == "unhedged":
            alerts.append({
                "level": "critical",
                "source": "polymarket",
                "message": (
                    f"Unhedged position requires manual intervention: "
                    f"{pos.market_question[:80]} (id={pos.id})"
                ),
            })
        elif pos.status == "stale":
            alerts.append({
                "level": "warning",
                "source": "polymarket",
                "message": (
                    f"Stale market position requires review: "
                    f"{pos.market_question[:80]} (id={pos.id})"
                ),
            })

    threshold = -(poly_config.daily_loss_limit * 0.80)
    if poly_realized_today < threshold:
        alerts.append({
            "level": "warning",
            "source": "polymarket",
            "message": (
                f"Daily P&L ({poly_realized_today:.2f} USDC) is within 20% "
                f"of the daily loss limit ({-poly_config.daily_loss_limit:.2f} USDC)"
            ),
        })

    if alpaca_error:
        alerts.append({
            "level": "warning",
            "source": "alpaca",
            "message": f"Alpaca data unavailable (showing cached): {alpaca_error}",
        })

    if poly_error:
        alerts.append({
            "level": "warning",
            "source": "polymarket",
            "message": f"Polymarket data unavailable (showing cached): {poly_error}",
        })

    return alerts


# ---------------------------------------------------------------------------
# P&L series from daily log
# ---------------------------------------------------------------------------

def _read_pnl_series(poly_log_dir: str) -> list[dict[str, Any]]:
    """Read today's poly daily log and return time-stamped P&L entries."""
    log_path = Path(poly_log_dir) / f"poly_{_today_date()}.log"
    if not log_path.exists():
        return []
    points: list[dict[str, Any]] = []
    try:
        with log_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                entry = json.loads(raw)
                points.append({
                    "ts": entry.get("ts", ""),
                    "combined_daily_pnl": float(entry.get("combined_daily_pnl", 0.0)),
                    "unrealized_pnl": float(entry.get("unrealized_pnl", 0.0)),
                    "realized_pnl_today": float(entry.get("realized_pnl_today", 0.0)),
                })
    except Exception as exc:
        LOGGER.warning("dashboard_pnl_series_fail path=%s error=%s", log_path, exc)
    return points


# ---------------------------------------------------------------------------
# BTC signal summary for snapshot
# ---------------------------------------------------------------------------

def _btc_signals_dict() -> dict[str, Any]:
    """Return a JSON-serializable dict of cached BTC signals."""
    s = get_cached_signals()
    if not s.data_available:
        return {"data_available": False}
    overall_bias = (
        "bullish" if s.change_24h_pct > 2 and s.rsi_14 < 70
        else "bearish" if s.change_24h_pct < -2 and s.rsi_14 > 30
        else "neutral"
    )
    signal_strength = min(100, int(abs(s.change_24h_pct) * 10 + (s.volume_ratio - 1) * 20))
    return {
        "data_available": True,
        "price_usd": s.price_usd,
        "change_24h_pct": s.change_24h_pct,
        "rsi_14": s.rsi_14,
        "macd_crossover": s.macd_crossover,
        "consecutive_bars": s.consecutive_bars,
        "streak_direction": s.streak_direction,
        "volume_ratio": s.volume_ratio,
        "bb_width_ratio": s.bb_width_ratio,
        "atr_ratio": s.atr_ratio,
        "overall_bias": overall_bias,
        "signal_strength": signal_strength,
    }


# ---------------------------------------------------------------------------
# Multi-venue balance helpers
# ---------------------------------------------------------------------------

def _fetch_hl_balance() -> float:
    """Return Hyperliquid clearinghouse accountValue in USDC, or 0.0 on any failure.

    Reads HL_WALLET_ADDRESS from the environment.  HL being down must never
    crash the dashboard — all errors are caught and logged as warnings.
    """
    hl_wallet = os.getenv("HL_WALLET_ADDRESS", "")
    if not hl_wallet:
        return 0.0
    try:
        import httpx
        resp = httpx.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "clearinghouseState", "user": hl_wallet},
            timeout=4,
        )
        m = resp.json().get("marginSummary", {})
        return float(m.get("accountValue", 0))
    except Exception as exc:
        LOGGER.warning("hl_balance_fetch_error error=%s", exc)
        return 0.0


def _load_total_deposited() -> float:
    """Read total_deposited from DEPOSITS_FILE (default: data/deposits.json).

    The file must be created manually on the server with format:
        {"total_deposited": 138.00, "as_of": "2026-04-25"}
    (138 = ~80 Polymarket pUSD + 60 HL - bridge fees)
    Returns 0.0 when the file is absent or unreadable.
    """
    deposits_path = Path(os.getenv("DEPOSITS_FILE", "data/deposits.json"))
    if not deposits_path.exists():
        return 0.0
    try:
        return float(json.loads(deposits_path.read_text()).get("total_deposited", 0))
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DashboardAggregator:
    """Builds unified snapshots from Alpaca (paper) and Polymarket data.

    Call build_snapshot() to get a full normalized snapshot dict.
    Results are cached for _SNAPSHOT_TTL_SEC seconds.
    Call update_opportunities() from the scanner to keep opps fresh.
    """

    poly_config: PolymarketConfig
    ledger: PositionsLedger
    repository: Any = None  # PersistenceRepository | None

    _cache: dict[str, Any] = field(default_factory=dict, repr=False)
    _cache_ts: float = field(default=0.0, repr=False)
    _last_alpaca: dict[str, Any] = field(default_factory=dict, repr=False)
    _last_poly: dict[str, Any] = field(default_factory=dict, repr=False)
    _last_opps: list[dict[str, Any]] = field(default_factory=list, repr=False)

    # -----------------------------------------------------------------------

    def update_opportunities(self, opps: list[Any]) -> None:
        """Cache the latest scan opportunities (called by scanner loop)."""
        self._last_opps = [
            {
                "strategy": o.strategy,
                "market_question": o.market_question,
                "edge_pct": o.edge_pct,
                "confidence": o.confidence,
                "action": o.action,
                "notes": o.notes,
                "condition_id": o.condition_id,
                "volume_24h": o.volume_24h,
                "direction": o.direction,
                "confidence_score": o.confidence_score,
                "rank_score": o.rank_score,
                "signal_notes": list(o.signal_notes),
            }
            for o in opps
        ]

    # -----------------------------------------------------------------------

    def _fetch_alpaca(self) -> dict[str, Any]:
        if self.repository is None:
            return {
                "cash": 0.0,
                "portfolio_value": 0.0,
                "buying_power": 0.0,
                "unrealized_pnl": 0.0,
                "realized_pnl_today": 0.0,
                "positions": [],
                "kill_switch": False,
                "bot_status": "unknown",
            }

        snapshot = self.repository.load_portfolio_snapshot(default_cash=100_000.0)
        kill_switch = self.repository.get_global_kill_switch()

        active = [p for p in snapshot.positions.values() if float(p.quantity) > 0]
        pos_value = sum(
            float(p.quantity) * float(p.avg_price) + float(p.unrealized_pnl)
            for p in active
        )
        unrealized = sum(float(p.unrealized_pnl) for p in active)
        realized = sum(float(p.realized_pnl) for p in active)

        return {
            "cash": float(snapshot.cash),
            "portfolio_value": round(float(snapshot.cash) + pos_value, 2),
            "buying_power": float(snapshot.cash),
            "unrealized_pnl": round(unrealized, 2),
            "realized_pnl_today": round(realized, 2),
            "positions": [normalize_alpaca_position(p) for p in active],
            "kill_switch": kill_switch,
            "bot_status": "paused" if kill_switch else "live",
        }

    def _fetch_poly(self) -> dict[str, Any]:
        positions = self.ledger.load()
        active = [p for p in positions if p.status in ACTIVE_STATUSES]
        all_active = positions  # include terminal for alert scan

        deployed = sum(p.size_usdc for p in active)
        unrealized = sum((p.unrealized_pnl or 0.0) for p in active)
        realized_today = self.ledger.daily_pnl()

        return {
            "deployed_usdc": round(deployed, 2),
            "unrealized_pnl": round(unrealized, 4),
            "realized_pnl_today": round(realized_today, 4),
            "open_count": self.ledger.open_count(),
            "positions": [normalize_poly_position(p) for p in active],
            "all_positions": all_active,
        }

    # -----------------------------------------------------------------------

    def build_snapshot(self, force: bool = False) -> dict[str, Any]:
        """Return the latest aggregated snapshot (cached for 30 s)."""
        now = time.monotonic()
        if not force and self._cache and (now - self._cache_ts) < _SNAPSHOT_TTL_SEC:
            return self._cache

        alpaca_error: str | None = None
        try:
            alpaca = self._fetch_alpaca()
            self._last_alpaca = alpaca
        except Exception as exc:
            LOGGER.error("dashboard_alpaca_fetch_fail error=%s", exc)
            alpaca = self._last_alpaca or {
                "cash": 0.0,
                "portfolio_value": 0.0,
                "buying_power": 0.0,
                "unrealized_pnl": 0.0,
                "realized_pnl_today": 0.0,
                "positions": [],
                "kill_switch": False,
                "bot_status": "unknown",
            }
            alpaca_error = str(exc)

        poly_error: str | None = None
        try:
            poly = self._fetch_poly()
            self._last_poly = poly
        except Exception as exc:
            LOGGER.error("dashboard_poly_fetch_fail error=%s", exc)
            poly = self._last_poly or {
                "deployed_usdc": 0.0,
                "unrealized_pnl": 0.0,
                "realized_pnl_today": 0.0,
                "open_count": 0,
                "positions": [],
                "all_positions": [],
            }
            poly_error = str(exc)

        hl_balance = _fetch_hl_balance()
        total_deposited = _load_total_deposited()

        poly_usdc = float(poly.get("deployed_usdc", 0.0))
        combined_value = float(alpaca.get("portfolio_value", 0)) + poly_usdc + hl_balance
        combined_unrealized = float(alpaca.get("unrealized_pnl", 0)) + float(poly.get("unrealized_pnl", 0))
        combined_today = float(alpaca.get("realized_pnl_today", 0)) + float(poly.get("realized_pnl_today", 0))

        poly_realized_today = float(poly.get("realized_pnl_today", 0.0))
        poly_loss_used = -poly_realized_today if poly_realized_today < 0 else 0.0
        limit = self.poly_config.daily_loss_limit
        poly_loss_pct = (poly_loss_used / limit * 100.0) if limit > 0 else 0.0

        all_poly: list[PositionRecord] = poly.get("all_positions", [])
        alerts = _build_alerts(
            poly_positions=all_poly,
            poly_config=self.poly_config,
            alpaca_kill_switch=bool(alpaca.get("kill_switch", False)),
            poly_realized_today=poly_realized_today,
            alpaca_error=alpaca_error,
            poly_error=poly_error,
        )

        pnl_series = _read_pnl_series(self.poly_config.poly_log_dir)

        equity = poly_usdc + hl_balance
        total_pnl = (equity - total_deposited) if total_deposited > 0 else 0.0

        snapshot: dict[str, Any] = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "equity": round(equity, 2),
            "equity_breakdown": {
                "polymarket_usdc": round(poly_usdc, 2),
                "hyperliquid_usdc": round(hl_balance, 2),
            },
            "total_pnl": round(total_pnl, 2),
            "total_deposited": total_deposited,
            "account": {
                "alpaca_cash": alpaca.get("cash", 0.0),
                "alpaca_portfolio_value": alpaca.get("portfolio_value", 0.0),
                "polymarket_deployed_usdc": poly_usdc,
                "hyperliquid_balance": round(hl_balance, 2),
                "combined_total_value": round(combined_value, 2),
            },
            "pnl": {
                "alpaca_unrealized": alpaca.get("unrealized_pnl", 0.0),
                "alpaca_realized_today": alpaca.get("realized_pnl_today", 0.0),
                "poly_unrealized": poly.get("unrealized_pnl", 0.0),
                "poly_realized_today": poly_realized_today,
                "combined_today": round(combined_today, 4),
                "combined_unrealized": round(combined_unrealized, 4),
            },
            "risk": {
                "poly_daily_loss_limit": limit,
                "poly_daily_loss_used": round(poly_loss_used, 2),
                "poly_daily_loss_pct": round(poly_loss_pct, 1),
                "poly_open_positions": poly.get("open_count", 0),
                "poly_max_positions": self.poly_config.max_positions,
                "poly_bot_status": poly_bot_status(self.poly_config),
                "alpaca_buying_power": alpaca.get("buying_power", 0.0),
                "alpaca_bot_status": alpaca.get("bot_status", "unknown"),
            },
            "alpaca_positions": alpaca.get("positions", []),
            "poly_positions": poly.get("positions", []),
            "poly_opportunities": self._last_opps[:5],
            "pnl_series": pnl_series,
            "alerts": alerts,
            "btc_signals": _btc_signals_dict(),
        }

        self._cache = snapshot
        self._cache_ts = now
        return snapshot
