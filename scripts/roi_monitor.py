#!/usr/bin/env python3
import os
import sys
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor

ENV_PATH = "/etc/trauto/env"


def get_database_url() -> str:
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return db_url
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("DATABASE_URL="):
                    return line.strip().split("=", 1)[1]
    except FileNotFoundError:
        pass
    raise SystemExit("DATABASE_URL not found in environment or /etc/trauto/env")


def fetch_all(cur, sql: str):
    cur.execute(sql)
    return cur.fetchall()


def fetch_one(cur, sql: str):
    cur.execute(sql)
    return cur.fetchone()


def fmt_money(v):
    v = float(v or 0.0)
    return f"${v:,.2f}"


def fmt_ts(ts):
    if not ts:
        return "-"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def main():
    db_url = get_database_url()
    with psycopg2.connect(db_url) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            totals = fetch_one(cur, """
                SELECT
                    COALESCE(SUM(realized_pnl), 0) AS total_realized_pnl,
                    COALESCE(SUM(unrealized_pnl), 0) AS total_unrealized_pnl,
                    COALESCE(SUM(realized_pnl + unrealized_pnl), 0) AS total_pnl,
                    COUNT(*) AS symbols,
                    MAX(updated_at) AS last_update
                FROM positions
            """)

            by_symbol = fetch_all(cur, """
                SELECT
                    symbol,
                    quantity,
                    avg_price,
                    realized_pnl,
                    unrealized_pnl,
                    realized_pnl + unrealized_pnl AS total_pnl,
                    updated_at
                FROM positions
                ORDER BY total_pnl DESC, updated_at DESC
            """)

            recent = fetch_all(cur, """
                SELECT
                    symbol,
                    quantity,
                    avg_price,
                    realized_pnl,
                    unrealized_pnl,
                    realized_pnl + unrealized_pnl AS total_pnl,
                    updated_at
                FROM positions
                ORDER BY updated_at DESC
                LIMIT 10
            """)

    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"Trauto ROI Monitor — {now}")
    print("=" * 72)
    print(f"Tracked symbols     : {totals['symbols']}")
    print(f"Realized PnL        : {fmt_money(totals['total_realized_pnl'])}")
    print(f"Unrealized PnL      : {fmt_money(totals['total_unrealized_pnl'])}")
    print(f"Total PnL           : {fmt_money(totals['total_pnl'])}")
    print(f"Last position update: {fmt_ts(totals['last_update'])}")
    print()

    print("Top symbols by total PnL")
    print("-" * 72)
    if not by_symbol:
        print("No rows found in positions table.")
    else:
        for row in by_symbol[:15]:
            print(
                f"{row['symbol']:<12} qty={row['quantity']:<12.6f} "
                f"avg={row['avg_price']:<12.6f} "
                f"realized={fmt_money(row['realized_pnl']):>12} "
                f"unrealized={fmt_money(row['unrealized_pnl']):>12} "
                f"total={fmt_money(row['total_pnl']):>12} "
                f"updated={fmt_ts(row['updated_at'])}"
            )
    print()

    print("Most recently updated positions")
    print("-" * 72)
    if not recent:
        print("No recent position activity.")
    else:
        for row in recent:
            print(
                f"{fmt_ts(row['updated_at'])}  {row['symbol']:<12} "
                f"qty={row['quantity']:<12.6f} total={fmt_money(row['total_pnl'])}"
            )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)