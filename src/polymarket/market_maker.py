"""Polymarket passive market-making module.

Strategy: quote symmetric bid/ask around the CLOB midpoint on high-volume
markets, refresh every 60s, earn spread + liquidity rewards.

Integration: call run_market_maker_cycle(config) from runner.py each loop.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

LOGGER = logging.getLogger("theta.polymarket.market_maker")

# ── tunables ────────────────────────────────────────────────────────────────
HALF_SPREAD     = 0.01    # ±1¢ around mid → 2¢ gross spread
MIN_MID         = 0.08    # skip near-resolved-NO markets
MAX_MID         = 0.92    # skip near-resolved-YES markets
MIN_VOL_24H     = 50_000  # minimum 24h USDC volume
MAX_MARKETS     = 5       # markets to quote simultaneously
QUOTE_SIZE_USDC = 0.18    # $ per side per market (fits $0.99 budget: 5×2×0.18=$1.80 max, but orders stagger)
REFRESH_SEC     = 60      # requote interval
STALE_TICK      = 0.005   # requote if mid moves >0.5¢
GAMMA_URL       = "https://gamma-api.polymarket.com/markets"
CLOB_URL        = "https://clob.polymarket.com"
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class QuotedMarket:
    condition_id:   str
    yes_token_id:   str
    no_token_id:    str
    question:       str
    mid:            float = 0.0
    bid_order_id:   str   = ""
    ask_order_id:   str   = ""
    last_quoted_at: float = 0.0


def _fetch_candidate_markets(timeout: float = 10.0) -> list[dict[str, Any]]:
    try:
        resp = httpx.get(
            GAMMA_URL,
            params={"active": "true", "closed": "false", "limit": 200,
                    "order": "volume24hr", "ascending": "false"},
            timeout=timeout,
        )
        resp.raise_for_status()
        raw = resp.json()
        markets = raw if isinstance(raw, list) else raw.get("markets", [])
    except Exception as exc:
        LOGGER.warning("mm_gamma_fetch_failed error=%s", exc)
        return []

    candidates = []
    for m in markets:
        vol = float(m.get("volume24hr") or m.get("volume") or 0)
        if vol < MIN_VOL_24H:
            continue
        tokens = m.get("tokens") or m.get("clobTokenIds") or []
        if len(tokens) < 2:
            continue
        yes_ask = float(m.get("bestAsk") or m.get("outcomePrices", [0.5])[0] or 0.5)
        mid = 1.0 - yes_ask if yes_ask > 0.5 else yes_ask
        if not (MIN_MID <= mid <= MAX_MID):
            continue
        t0, t1 = tokens[0], tokens[1]
        candidates.append({
            "condition_id": m.get("conditionId") or m.get("id", ""),
            "yes_token_id": str(t0) if isinstance(t0, (int, str)) else t0.get("token_id", ""),
            "no_token_id":  str(t1) if isinstance(t1, (int, str)) else t1.get("token_id", ""),
            "question":     m.get("question", "")[:80],
            "mid":          mid,
            "vol":          vol,
        })
        if len(candidates) >= MAX_MARKETS:
            break
    return candidates


def _get_midpoint(yes_token_id: str, timeout: float = 5.0) -> float | None:
    try:
        resp = httpx.get(f"{CLOB_URL}/midpoint",
                         params={"token_id": yes_token_id}, timeout=timeout)
        if resp.status_code == 200:
            return float(resp.json().get("mid", 0))
    except Exception:
        pass
    return None


def _cancel_order(client: Any, order_id: str) -> None:
    if not order_id:
        return
    try:
        client.cancel(order_id=order_id)
        LOGGER.info("mm_order_cancelled order_id=%s", order_id)
    except Exception as exc:
        LOGGER.warning("mm_cancel_failed order_id=%s error=%s", order_id, exc)


def _place_gtc_order(client: Any, token_id: str, side: str,
                     price: float, size_usdc: float) -> str:
    from py_clob_client_v2.clob_types import OrderArgs, OrderType
    from py_clob_client_v2.order_builder.constants import BUY, SELL
    price = round(max(0.01, min(0.99, price)), 2)
    size_contracts = round(size_usdc / price, 4) if price > 0 else 0
    if size_contracts <= 0:
        return ""
    try:
        signed = client.create_order(OrderArgs(
            token_id=token_id, price=price, size=size_contracts,
            side=BUY if side == "BUY" else SELL,
        ))
        resp = client.post_order(signed, OrderType.GTC)
        oid = resp.get("orderID") or resp.get("order_id") or ""
        LOGGER.info("mm_order_placed side=%s token=%.8s price=%.2f size_usdc=%.2f oid=%s",
                    side, token_id, price, size_usdc, oid)
        return oid
    except Exception as exc:
        LOGGER.warning("mm_order_failed side=%s token=%.8s price=%.2f error=%s",
                       side, token_id, price, exc)
        return ""


class MarketMaker:
    def __init__(self, config: Any) -> None:
        self.config = config
        self._quoted: dict[str, QuotedMarket] = {}
        self._last_refresh: float = 0.0

    def _make_client(self) -> Any:
        from py_clob_client_v2.client import ClobClient
        from py_clob_client_v2.clob_types import ApiCreds
        return ClobClient(
            CLOB_URL, key=self.config.private_key, chain_id=137,
            creds=ApiCreds(api_key=self.config.api_key,
                           api_secret=self.config.api_secret,
                           api_passphrase=self.config.passphrase),
        )

    def _refresh_markets(self) -> None:
        now = time.time()
        if now - self._last_refresh < 300:
            return
        candidates = _fetch_candidate_markets()
        LOGGER.info("mm_market_refresh candidates=%d", len(candidates))
        active_cids = {c["condition_id"] for c in candidates}

        for c in candidates:
            cid = c["condition_id"]
            if cid not in self._quoted:
                self._quoted[cid] = QuotedMarket(**{k: c[k] for k in
                    ("condition_id","yes_token_id","no_token_id","question","mid")})
                LOGGER.info("mm_market_added cid=%.12s question=%s mid=%.2f",
                            cid, c["question"], c["mid"])

        stale = [cid for cid in self._quoted if cid not in active_cids]
        if stale:
            client = self._make_client()
            for cid in stale:
                qm = self._quoted.pop(cid)
                _cancel_order(client, qm.bid_order_id)
                _cancel_order(client, qm.ask_order_id)
                LOGGER.info("mm_market_dropped cid=%.12s", cid)

        self._last_refresh = now

    def _requote(self, client: Any, qm: QuotedMarket) -> None:
        now = time.time()
        live_mid = _get_midpoint(qm.yes_token_id)
        if live_mid is None:
            return
        moved = abs(live_mid - qm.mid) if qm.mid else STALE_TICK + 1
        if now - qm.last_quoted_at < REFRESH_SEC and moved < STALE_TICK:
            return
        if not (MIN_MID <= live_mid <= MAX_MID):
            return

        _cancel_order(client, qm.bid_order_id)
        _cancel_order(client, qm.ask_order_id)
        qm.bid_order_id = qm.ask_order_id = ""

        bid_price    = round(live_mid - HALF_SPREAD, 2)
        no_bid_price = round(1.0 - (live_mid + HALF_SPREAD), 2)

        if self.config.dry_run:
            LOGGER.info(
                "mm_dry_run_quote cid=%.12s question=%s mid=%.3f "
                "YES_bid=%.2f NO_bid=%.2f size_usdc=%.2f",
                qm.condition_id, qm.question, live_mid,
                bid_price, no_bid_price, QUOTE_SIZE_USDC,
            )
        else:
            qm.bid_order_id = _place_gtc_order(client, qm.yes_token_id, "BUY", bid_price, QUOTE_SIZE_USDC)
            qm.ask_order_id = _place_gtc_order(client, qm.no_token_id,  "BUY", no_bid_price, QUOTE_SIZE_USDC)

        qm.mid = live_mid
        qm.last_quoted_at = now

    def run_once(self) -> None:
        self._refresh_markets()
        if not self._quoted:
            LOGGER.info("mm_no_markets_quoted")
            return
        client = self._make_client()
        for cid, qm in list(self._quoted.items()):
            try:
                self._requote(client, qm)
            except Exception as exc:
                LOGGER.warning("mm_requote_error cid=%.12s error=%s", cid, exc)
        LOGGER.info("mm_cycle_complete quoted_markets=%d", len(self._quoted))

    def cancel_all(self) -> None:
        client = self._make_client()
        for qm in self._quoted.values():
            _cancel_order(client, qm.bid_order_id)
            _cancel_order(client, qm.ask_order_id)
        LOGGER.info("mm_all_cancelled count=%d", len(self._quoted))


_MM_INSTANCE: MarketMaker | None = None


def run_market_maker_cycle(config: Any) -> None:
    """Top-level entry — call this from runner.py each scan loop."""
    global _MM_INSTANCE
    if _MM_INSTANCE is None:
        _MM_INSTANCE = MarketMaker(config)
    _MM_INSTANCE.run_once()
