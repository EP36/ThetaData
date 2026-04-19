"""Signal backtest — replays BTC signal scoring against historical Alpaca bars.

Usage:
  python -m src.polymarket.backtest \
      --markets markets.json \
      --start 2024-01-01 \
      --end   2024-03-31 \
      --out   backtest_results.csv

markets.json must be a list of objects matching the Opportunity fields:
  [{"strategy":"...", "market_question":"...", "edge_pct":2.0, "action":"...",
    "confidence":"medium", "notes":"..."}]

The script fetches historical hourly BTC/USD bars from Alpaca, steps through
each 24-hour window, computes BtcSignals for that window, scores every market
from the JSON file, and records the scoring decision.  Output CSV columns:

  date, strategy, market_question, direction, confidence, edge_pct,
  confidence_score, rank_score, signal_notes, btc_price, change_24h_pct,
  rsi_14, macd_crossover, volume_ratio

Exit codes: 0 = success, 1 = missing credentials or fetch failure.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd

from src.config.alpaca import read_alpaca_api_key, read_alpaca_api_secret, read_alpaca_data_base_url
from src.polymarket.alpaca_signals import (
    BtcSignals,
    _atr_ratio,
    _bb_width_ratio,
    _consecutive_bars,
    _macd_crossover,
    _rsi,
    _volume_ratio,
)
from src.polymarket.opportunities import Opportunity
from src.polymarket.signals import score_opportunity

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("theta.polymarket.backtest")

_CRYPTO_PATH = "/v1beta3/crypto/us/bars"
_SYMBOL = "BTC/USD"
_TIMEFRAME = "1H"

CSV_FIELDS = [
    "date", "strategy", "market_question", "direction", "confidence",
    "edge_pct", "confidence_score", "rank_score", "signal_notes",
    "btc_price", "change_24h_pct", "rsi_14", "macd_crossover", "volume_ratio",
]


def _fetch_historical_bars(start: str, end: str, timeout: float = 30.0) -> pd.DataFrame:
    """Fetch all hourly BTC bars between start and end from Alpaca."""
    import httpx

    api_key = read_alpaca_api_key()
    api_secret = read_alpaca_api_secret()
    if not api_key or not api_secret:
        LOGGER.error("Missing ALPACA_API_KEY / ALPACA_API_SECRET — cannot fetch bars")
        sys.exit(1)

    base_url = read_alpaca_data_base_url()
    bars: list[dict] = []
    page_token: str | None = None

    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        while True:
            params: dict = {
                "symbols": _SYMBOL,
                "timeframe": _TIMEFRAME,
                "start": start,
                "end": end,
                "sort": "asc",
                "limit": "10000",
            }
            if page_token:
                params["page_token"] = page_token

            resp = client.get(
                _CRYPTO_PATH,
                params=params,
                headers={
                    "APCA-API-KEY-ID": api_key,
                    "APCA-API-SECRET-KEY": api_secret,
                },
            )
            try:
                resp.raise_for_status()
            except Exception as exc:
                LOGGER.error("Alpaca fetch failed: %s", exc)
                sys.exit(1)

            payload = resp.json()
            chunk = payload.get("bars", {}).get(_SYMBOL, [])
            bars.extend(chunk)
            page_token = payload.get("next_page_token")
            if not page_token:
                break

    if not bars:
        LOGGER.error("No bars returned for %s %s→%s", _SYMBOL, start, end)
        sys.exit(1)

    df = pd.DataFrame({
        "ts":     [b.get("t") for b in bars],
        "close":  [float(b.get("c", 0)) for b in bars],
        "high":   [float(b.get("h", 0)) for b in bars],
        "low":    [float(b.get("l", 0)) for b in bars],
        "volume": [float(b.get("v", 0)) for b in bars],
    })
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    LOGGER.info("Fetched %d hourly bars (%s → %s)", len(df), df["ts"].iloc[0], df["ts"].iloc[-1])
    return df


def _signals_for_window(df: pd.DataFrame, idx: int) -> BtcSignals:
    """Compute BtcSignals for bars[0:idx] (up to idx, not inclusive of future)."""
    window = df.iloc[:idx]
    if len(window) < 2:
        return BtcSignals(data_available=False)

    closes  = window["close"]
    highs   = window["high"]
    lows    = window["low"]
    volumes = window["volume"]

    price_usd  = float(closes.iloc[-1])
    price_24h  = float(closes.iloc[-25]) if len(closes) >= 25 else float(closes.iloc[0])
    change_24h = (price_usd - price_24h) / price_24h * 100.0 if price_24h != 0 else 0.0
    streak_count, streak_dir = _consecutive_bars(closes)

    return BtcSignals(
        data_available=True,
        price_usd=round(price_usd, 2),
        change_24h_pct=round(change_24h, 4),
        rsi_14=round(_rsi(closes), 2),
        macd_crossover=_macd_crossover(closes),
        consecutive_bars=streak_count,
        streak_direction=streak_dir,
        volume_ratio=round(_volume_ratio(volumes), 4),
        bb_width_ratio=round(_bb_width_ratio(closes), 4),
        atr_ratio=round(_atr_ratio(highs, lows, closes), 4),
        fetched_at=time.monotonic(),
    )


def _load_markets(path: str) -> list[Opportunity]:
    raw = json.loads(Path(path).read_text())
    opps = []
    for item in raw:
        opps.append(Opportunity(
            strategy=item.get("strategy", ""),
            market_question=item.get("market_question", ""),
            edge_pct=float(item.get("edge_pct", 0)),
            action=item.get("action", ""),
            confidence=item.get("confidence", "medium"),
            notes=item.get("notes", ""),
        ))
    return opps


def run_backtest(
    markets_path: str,
    start: str,
    end: str,
    out_path: str,
    step_hours: int = 24,
) -> None:
    """Run the signal backtest and write results to a CSV file."""
    markets = _load_markets(markets_path)
    LOGGER.info("Loaded %d markets from %s", len(markets), markets_path)

    bars = _fetch_historical_bars(start, end)

    rows: list[dict] = []
    # Step through bars daily (every step_hours bars)
    window_start = max(30, step_hours)  # need enough bars for indicators
    for idx in range(window_start, len(bars) + 1, step_hours):
        signals = _signals_for_window(bars, idx)
        if not signals.data_available:
            continue
        date_label = str(bars["ts"].iloc[idx - 1].date())

        scored = [score_opportunity(m, signals) for m in markets]
        scored.sort(key=lambda o: o.rank_score, reverse=True)

        for opp in scored:
            rows.append({
                "date": date_label,
                "strategy": opp.strategy,
                "market_question": opp.market_question,
                "direction": opp.direction,
                "confidence": opp.confidence,
                "edge_pct": opp.edge_pct,
                "confidence_score": opp.confidence_score,
                "rank_score": opp.rank_score,
                "signal_notes": " | ".join(opp.signal_notes),
                "btc_price": signals.price_usd,
                "change_24h_pct": signals.change_24h_pct,
                "rsi_14": signals.rsi_14,
                "macd_crossover": signals.macd_crossover,
                "volume_ratio": signals.volume_ratio,
            })

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    LOGGER.info(
        "Backtest complete: %d rows across %d dates written to %s",
        len(rows),
        len(set(r["date"] for r in rows)),
        out_path,
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Polymarket signal backtest")
    p.add_argument("--markets", required=True, help="Path to markets JSON file")
    p.add_argument("--start",   required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--end",     required=True, help="End date YYYY-MM-DD")
    p.add_argument("--out",     default="backtest_results.csv", help="Output CSV path")
    p.add_argument("--step-hours", type=int, default=24, help="Hours between scoring windows")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_backtest(
        markets_path=args.markets,
        start=args.start,
        end=args.end,
        out_path=args.out,
        step_hours=args.step_hours,
    )
