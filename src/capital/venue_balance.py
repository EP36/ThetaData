"""VenueBalanceProbe — queries free (undeployed) capital at each venue.

Returns a VenueSnapshot per venue with:
  free_usd    : capital available for new positions (not locked in open trades)
  locked_usd  : capital currently deployed / collateralising open positions
  total_usd   : free + locked

All methods return 0.0 on error and log at debug level so the rebalancer
can degrade gracefully when a venue is unreachable.

Venue identifiers (used as keys everywhere):
  "polymarket"  — Polygon USDC.e in CLOB v2 wallet
  "hyperliquid" — HL vault margin balance
  "coinbase"    — Coinbase Advanced Trade USDC balance
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

LOGGER = logging.getLogger("theta.capital.venue_balance")

HL_BASE_URL = "https://api.hyperliquid.xyz"


@dataclass
class VenueSnapshot:
    venue: str
    free_usd: float
    locked_usd: float
    total_usd: float
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Hyperliquid
# ---------------------------------------------------------------------------

def _hl_account_balance(wallet: str) -> dict[str, float]:
    """Returns {free_usd, locked_usd} from HL clearinghouse state."""
    try:
        resp = httpx.post(
            f"{HL_BASE_URL}/info",
            json={"type": "clearinghouseState", "user": wallet},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        margin = data.get("crossMarginSummary", {})
        total     = float(margin.get("accountValue", 0))
        margin_used = float(margin.get("totalMarginUsed", 0))
        free      = max(0.0, total - margin_used)
        return {"free_usd": round(free, 4), "locked_usd": round(margin_used, 4), "raw": margin}
    except Exception as exc:
        LOGGER.debug("hl_balance_failed wallet=%s error=%s", wallet[:8], exc)
        return {"free_usd": 0.0, "locked_usd": 0.0, "raw": {}}


def probe_hyperliquid() -> VenueSnapshot:
    wallet = os.getenv("HL_WALLET", "").strip()
    if not wallet:
        LOGGER.warning("venue_balance_skip venue=hyperliquid reason=HL_WALLET_not_set")
        return VenueSnapshot(venue="hyperliquid", free_usd=0.0, locked_usd=0.0, total_usd=0.0)
    b = _hl_account_balance(wallet)
    snap = VenueSnapshot(
        venue="hyperliquid",
        free_usd=b["free_usd"],
        locked_usd=b["locked_usd"],
        total_usd=round(b["free_usd"] + b["locked_usd"], 4),
        raw=b.get("raw", {}),
    )
    LOGGER.info(
        "venue_balance venue=hyperliquid free=%.2f locked=%.2f total=%.2f",
        snap.free_usd, snap.locked_usd, snap.total_usd,
    )
    return snap


# ---------------------------------------------------------------------------
# Coinbase
# ---------------------------------------------------------------------------

def probe_coinbase() -> VenueSnapshot:
    """Free USDC on Coinbase. Coinbase has no locked/collateral concept for spot."""
    try:
        from funding_arb.coinbase_client import get_spot_balance
        usdc = get_spot_balance("USDC")
        snap = VenueSnapshot(
            venue="coinbase",
            free_usd=round(usdc, 4),
            locked_usd=0.0,
            total_usd=round(usdc, 4),
        )
        LOGGER.info(
            "venue_balance venue=coinbase free=%.2f locked=0.00 total=%.2f",
            snap.free_usd, snap.total_usd,
        )
        return snap
    except Exception as exc:
        LOGGER.debug("coinbase_balance_probe_failed error=%s", exc)
        return VenueSnapshot(venue="coinbase", free_usd=0.0, locked_usd=0.0, total_usd=0.0)


# ---------------------------------------------------------------------------
# Polymarket
# ---------------------------------------------------------------------------

def probe_polymarket() -> VenueSnapshot:
    """Query USDC.e free balance on Polygon for the POLY_WALLET.

    Uses a simple ERC-20 balanceOf call via the public Polygon JSON-RPC.
    Locked collateral is not tracked on-chain directly; we report 0 for locked.
    """
    wallet = os.getenv("POLY_WALLET", "").strip()
    if not wallet:
        LOGGER.warning("venue_balance_skip venue=polymarket reason=POLY_WALLET_not_set")
        return VenueSnapshot(venue="polymarket", free_usd=0.0, locked_usd=0.0, total_usd=0.0)

    # USDC.e on Polygon
    USDC_E_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")

    # ERC-20 balanceOf selector: 0x70a08231
    padded = wallet.lower().replace("0x", "").zfill(64)
    call_data = "0x70a08231" + padded

    try:
        resp = httpx.post(
            RPC_URL,
            json={
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": USDC_E_CONTRACT, "data": call_data}, "latest"],
                "id": 1,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        result = resp.json().get("result", "0x0")
        raw_balance = int(result, 16)  # USDC.e has 6 decimals
        usdc = raw_balance / 1e6
        snap = VenueSnapshot(
            venue="polymarket",
            free_usd=round(usdc, 4),
            locked_usd=0.0,   # locked collateral not queryable without Polymarket API
            total_usd=round(usdc, 4),
        )
        LOGGER.info(
            "venue_balance venue=polymarket free=%.2f locked=0.00 total=%.2f",
            snap.free_usd, snap.total_usd,
        )
        return snap
    except Exception as exc:
        LOGGER.debug("polymarket_balance_probe_failed error=%s", exc)
        return VenueSnapshot(venue="polymarket", free_usd=0.0, locked_usd=0.0, total_usd=0.0)


def probe_all() -> dict[str, VenueSnapshot]:
    """Query all venues and return a dict keyed by venue name."""
    snaps = {
        "hyperliquid": probe_hyperliquid(),
        "coinbase":    probe_coinbase(),
        "polymarket":  probe_polymarket(),
    }
    total = sum(s.total_usd for s in snaps.values())
    LOGGER.info("venue_balance_total_usd=%.2f", total)
    return snaps
