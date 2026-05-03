"""Trade telemetry: structured per-trade records written as JSON lines.

Every executed (or attempted) order produces a TradeRecord.  Records are:
  - Logged at INFO level via the standard logger.
  - Appended as a JSON line to logs/trades.jsonl (one record per line).

The JSONL file is easy to analyse with pandas or jq:
    jq . logs/trades.jsonl
    python -c "import pandas as pd; print(pd.read_json('logs/trades.jsonl', lines=True))"

Fields marked "populated_after_fill" are 0.0 at submission time; a later
polling call would update them (not implemented here — kept intentionally
simple for v1).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger("theta.telemetry.trade_log")


@dataclass
class TradeRecord:
    """One complete record of a trade attempt (submitted, dry-run, or failed).

    All monetary values are in USD.  Prices are in quote-currency units.
    """
    # Identity
    timestamp: str              # ISO-8601 UTC, set at order-creation time
    exchange: str               # "coinbase"
    asset: str                  # base currency, e.g. "ETH"
    quote: str                  # quote currency, e.g. "USD"
    side: str                   # "buy" | "sell"

    # Intent
    notional_usd: float         # intended spend/proceeds in USD
    expected_edge_bps: float    # caller's alpha estimate in bps (0 if unknown)

    # Pre-trade market snapshot
    mid_price_at_order: float   # (best_bid + best_ask) / 2 at order time

    # Pre-trade cost model
    expected_fee_usd: float
    expected_slippage_usd: float
    expected_total_cost_usd: float

    # Exchange identifiers
    order_id: str
    client_order_id: str

    # Outcome
    status: str                 # "live" | "dry_run" | "failed" | "rejected"
                                # ("submitted" is the legacy label for "live")
    error: str = ""

    # Populated after fill (via polling — not set synchronously by Coinbase IOC)
    realized_fill_price: float = 0.0
    realized_qty: float = 0.0
    realized_fee_usd: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @staticmethod
    def make_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()


def log_trade(
    record: TradeRecord,
    log_dir: str = "logs",
    strategy_name: str = "",
) -> None:
    """Write a TradeRecord to the logger, JSONL file, and Postgres (if DATABASE_URL set)."""
    LOGGER.info(
        "trade_record exchange=%s asset=%s quote=%s side=%s "
        "notional=%.2f mid=%.6f edge=%.1fbps "
        "exp_fee=%.4f exp_slip=%.4f status=%s order_id=%s",
        record.exchange, record.asset, record.quote, record.side,
        record.notional_usd, record.mid_price_at_order,
        record.expected_edge_bps,
        record.expected_fee_usd, record.expected_slippage_usd,
        record.status, record.order_id,
    )

    try:
        out_dir = Path(log_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = out_dir / "trades.jsonl"
        LOGGER.info("trade_log_path abs=%s", jsonl_path)
        with open(jsonl_path, "a", encoding="utf-8") as fh:
            fh.write(record.to_json() + "\n")
    except Exception as exc:
        LOGGER.warning("trade_log_write_failed path=%s error=%s", log_dir, exc)

    if strategy_name:
        try:
            from theta.db.writer import write_trade
            write_trade(record, strategy_name)
        except Exception as exc:
            LOGGER.warning("trade_db_write_failed strategy=%s error=%s", strategy_name, exc)
