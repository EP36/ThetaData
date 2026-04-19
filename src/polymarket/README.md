# Polymarket CLOB Arb Scanner

Phase 1: connection and scanning only. No orders are submitted.

## What it does

Connects to Polymarket's CLOB API and scans active Bitcoin prediction
markets for three types of mispricing:

| Strategy | Description |
|---|---|
| `orderbook_spread` | Riskless arb when `YES_ask + NO_ask + fee < $1.00` |
| `cross_market` | Price discrepancy between matched Polymarket and Kalshi questions |
| `correlated_markets` | Dominance violation: P(BTC > $X) > P(BTC > $Y) where X < Y |

Each opportunity is logged as a structured `key=value` line and returned
as an `Opportunity` dataclass with `strategy`, `market_question`,
`edge_pct`, `action`, `confidence`, and `notes`.

## Environment variables

Set these in your `.env` file (see root `.env.example`):

| Variable | Required | Default | Description |
|---|---|---|---|
| `POLY_API_KEY` | Yes | — | Polymarket API key |
| `POLY_API_SECRET` | Yes | — | HMAC signing secret |
| `POLY_PASSPHRASE` | Yes | — | API passphrase |
| `POLY_PRIVATE_KEY` | Yes | — | Wallet private key (for L2 auth in Phase 2) |
| `POLY_SCAN_INTERVAL_SEC` | No | `30` | Seconds between scan cycles |
| `POLY_MIN_EDGE_PCT` | No | `1.5` | Minimum edge % to report an opportunity |
| `POLY_CLOB_BASE_URL` | No | `https://clob.polymarket.com` | CLOB API base URL |
| `KALSHI_BASE_URL` | No | `https://trading-api.kalshi.com/trade-api/v2` | Kalshi base URL |
| `POLY_MAX_RETRIES` | No | `3` | HTTP retry attempts on transient errors |
| `POLY_TIMEOUT_SECONDS` | No | `15.0` | Per-request timeout |

Obtain API credentials at https://polymarket.com (developer settings).
Public GET endpoints (markets, orderbooks) work without credentials for
testing, but `PolymarketConfig.from_env()` validates that all four
credential fields are non-empty.

## Run standalone

```bash
# Set credentials
export POLY_API_KEY=...
export POLY_API_SECRET=...
export POLY_PASSPHRASE=...
export POLY_PRIVATE_KEY=...

python -m src.polymarket
```

The scanner loops every `POLY_SCAN_INTERVAL_SEC` seconds and logs all
opportunities to `logs/system.log` and stdout.

## Programmatic use

```python
from src.polymarket import PolymarketConfig, scan

config = PolymarketConfig.from_env()
opportunities = scan(config)   # returns list[Opportunity]
```

## Run tests

```bash
pytest tests/polymarket/
```

## Module layout

```
src/polymarket/
├── __init__.py          # Public API: scan(), Opportunity, PolymarketConfig
├── __main__.py          # Entrypoint: python -m src.polymarket
├── config.py            # PolymarketConfig dataclass + from_env()
├── client.py            # ClobClient (HTTP + L1 auth + retry)
├── scanner.py           # fetch_btc_markets(), fetch_market_orderbooks()
├── opportunities.py     # detect_orderbook_spread / cross_market / correlated
├── runner.py            # scan() — single cycle, importable by orchestrator
└── README.md

tests/polymarket/
├── test_config.py        # Config loading and validation
├── test_client.py        # Auth headers and retry logic
└── test_opportunities.py # All three arb detectors (mocked data)
```

## Phase 2 — trade execution (not yet implemented)

To enable execution the next phase would need to:

1. Add `ClobClient.submit_order(token_id, side, size, price)` using L2
   (EIP-712 wallet signature via `POLY_PRIVATE_KEY`).
2. Add position tracking (persist open legs so the scanner can skip
   already-entered opportunities).
3. Wire the `scan()` return value into a sizing and gating layer similar
   to `src/trading/sizing.py` and `src/trading/gating.py`.
4. Add a `POLY_ENABLE_TRADING=false` kill-switch env var (mirroring
   `WORKER_ENABLE_TRADING`) before any live order path is merged.
