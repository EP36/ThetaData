#!/usr/bin/env python
import os
import sys
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import DictCursor

def get_db_url():
    env_path = "/etc/trauto/env"
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return db_url

    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith("DATABASE_URL="):
                    return line.strip().split("=", 1)[1]

    print("DATABASE_URL not found in environment or /etc/trauto/env", file=sys.stderr)
    sys.exit(1)

def query_one(cur, sql, params=None):
    cur.execute(sql, params or {})
    row = cur.fetchone()
    return row[0] if row else 0.0

def main():
    db_url = get_db_url()

    lookback_hours = int(os.environ.get("ROI_LOOKBACK_HOURS", "24"))
    since = datetime.utcnow() - timedelta(hours=lookback_hours)

    conn = psycopg2.connect(db_url)
    try:
        with conn, conn.cursor(cursor_factory=DictCursor) as cur:
            print(f"=== Trauto ROI Monitor (last {lookback_hours}h) ===")
            print(f"Since: {since.isoformat(timespec='seconds')}Z\n")

            # 1) Funding arb PnL
            funding_sql_total = """
                SELECT COALESCE(SUM(net_pnl_usd), 0)
                FROM funding_arb_trades
                WHERE closed_at >= %(since)s
            """
            funding_sql_by_asset = """
                SELECT asset,
                       COALESCE(SUM(net_pnl_usd), 0) AS pnl,
                       COUNT(*) AS trades
                FROM funding_arb_trades
                WHERE closed_at >= %(since)s
                GROUP BY asset
                ORDER BY pnl DESC
                LIMIT 10
            """

            # 2) Polymarket PnL
            poly_sql_total = """
                SELECT COALESCE(SUM(net_pnl_usd), 0)
                FROM polymarket_positions
                WHERE closed_at >= %(since)s
                  AND status = 'closed'
            """
            poly_sql_by_market = """
                SELECT market_id,
                       COALESCE(SUM(net_pnl_usd), 0) AS pnl,
                       COUNT(*) AS trades
                FROM polymarket_positions
                WHERE closed_at >= %(since)s
                  AND status = 'closed'
                GROUP BY market_id
                ORDER BY pnl DESC
                LIMIT 10
            """

            funding_total = query_one(cur, funding_sql_total, {"since": since})
            poly_total = query_one(cur, poly_sql_total, {"since": since})
            total = funding_total + poly_total

            print(f"Funding arb PnL:    ${funding_total:,.2f}")
            print(f"Polymarket PnL:     ${poly_total:,.2f}")
            print(f"TOTAL PnL (24h):    ${total:,.2f}\n")

            print("Top funding arb assets:")
            cur.execute(funding_sql_by_asset, {"since": since})
            for row in cur.fetchall():
                print(f"  {row['asset']}: PnL ${row['pnl']:,.2f} over {row['trades']} trades")

            print("\nTop Polymarket markets:")
            cur.execute(poly_sql_by_market, {"since": since})
            for row in cur.fetchall():
                print(f"  {row['market_id']}: PnL ${row['pnl']:,.2f} over {row['trades']} trades")

    finally:
        conn.close()

if __name__ == "__main__":
    main()