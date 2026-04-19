# Polymarket CLOB Arb Scanner

Phases 1–4 of the Trauto Polymarket module: scan, execute, monitor, and dashboard.

---

## Running Trauto

### Phase 1 — scan only (no orders, no state)

```bash
python -m src.polymarket
```

Loops every `POLY_SCAN_INTERVAL_SEC` seconds, logs all opportunities.
No positions are opened; safe to run without credentials configured
(public CLOB endpoints work unauthenticated).

### Phase 2 — scanner + gated executor

Set `POLY_DRY_RUN=false` (and configure all four credential env vars) to
enable live execution. The scanner still runs on the same loop but the top
opportunity is now submitted to the CLOB API when all seven risk checks pass.

```bash
POLY_DRY_RUN=false python -m src.polymarket
```

### Phase 3 — scanner + executor + position monitor

Position monitoring runs on its own `POLY_MONITOR_INTERVAL_SEC` cadence
inside the same process. No extra command needed — monitor is wired into
`__main__.py` automatically.

### Phase 4 — full stack including dashboard

Start the FastAPI API server (includes the unified dashboard at `/`):

```bash
python -m src.api
```

Then open **http://localhost:8000** (or `DASHBOARD_PORT` if you've
redirected the port).

Start the Polymarket scanner separately (or in the same process tree):

```bash
python -m src.polymarket
```

The dashboard reads Polymarket positions from the JSON ledger file
(`POLY_POSITIONS_PATH`) and Alpaca paper positions from the SQLite DB —
both can run in separate processes without coordination.

#### One-liner (development)

```bash
# Terminal 1 — API + dashboard
python -m src.api

# Terminal 2 — Polymarket scanner
python -m src.polymarket
```

---

## Environment variables — complete reference

| Variable | Phase | Default | Description |
|---|---|---|---|
| `POLY_API_KEY` | 1 | — | Polymarket API key (required) |
| `POLY_API_SECRET` | 1 | — | HMAC signing secret (required) |
| `POLY_PASSPHRASE` | 1 | — | API passphrase (required) |
| `POLY_PRIVATE_KEY` | 1 | — | Wallet private key for L2 order signing (required) |
| `POLY_SCAN_INTERVAL_SEC` | 1 | `30` | Seconds between scan cycles |
| `POLY_MIN_EDGE_PCT` | 1 | `1.5` | Minimum edge % to surface an opportunity |
| `POLY_CLOB_BASE_URL` | 1 | `https://clob.polymarket.com` | CLOB API base URL |
| `KALSHI_BASE_URL` | 1 | `https://trading-api.kalshi.com/trade-api/v2` | Kalshi comparison endpoint |
| `POLY_MAX_RETRIES` | 1 | `3` | HTTP retry attempts on transient errors |
| `POLY_TIMEOUT_SECONDS` | 1 | `15.0` | Per-request HTTP timeout |
| `POLY_MIN_VOLUME_24H` | 1 | `10000` | Min 24 h USDC volume to consider a market |
| `POLY_MAX_TRADE_USDC` | 2 | `500` | Maximum USDC per trade |
| `POLY_MAX_POSITIONS` | 2 | `5` | Maximum concurrent open positions |
| `POLY_DAILY_LOSS_LIMIT` | 2 | `200` | Stop trading when daily P&L < −limit |
| `POLY_DRY_RUN` | 2 | `true` | `true` = log intent only, never place orders |
| `POLY_POSITIONS_PATH` | 2 | `data/polymarket_positions.json` | Positions ledger file path |
| `POLY_MONITOR_INTERVAL_SEC` | 3 | `60` | How often monitor_positions() runs |
| `POLY_TAKE_PROFIT_PCT` | 3 | `15.0` | Close when unrealized P&L ≥ this % |
| `POLY_STOP_LOSS_PCT` | 3 | `10.0` | Close when unrealized P&L ≤ −this % |
| `POLY_MAX_HOLD_HOURS` | 3 | `72` | Force-close after this many hours open |
| `POLY_UNHEDGED_GRACE_MINUTES` | 3 | `5` | Attempt close of unhedged leg after this many minutes |
| `POLY_LOG_DIR` | 3 | `logs` | Directory for `poly_YYYY-MM-DD.log` daily summaries |
| `DASHBOARD_PORT` | 4 | `8080` | Port for the combined API + dashboard server |
| `DASHBOARD_API_TOKEN` | 4 | — | Bearer token required for all POST dashboard actions |

---

## Architecture — how the four phases connect

```
┌─────────────────────────────────────────────────────┐
│                  python -m src.api                  │
│  FastAPI (src/api/app.py)                           │
│                                                     │
│  ┌─────────────────┐   ┌────────────────────────┐  │
│  │  Existing routes│   │  Phase 4: poly_dashboard│  │
│  │  /api/dashboard │   │  GET  /api/snapshot     │  │
│  │  /api/analytics │   │  GET  /api/positions    │  │
│  │  /api/trades    │   │  GET  /api/opportunities│  │
│  │  /api/auth      │   │  POST /api/poly/pause   │  │
│  │  /healthz       │   │  POST /api/poly/close/* │  │
│  └─────────────────┘   │  GET  /  (HTML UI)      │  │
│                         └────────────────────────┘  │
│  DashboardAggregator (src/dashboard/aggregator.py)  │
│    ├── Alpaca data: PersistenceRepository (SQLite)  │
│    └── Poly data:  PositionsLedger (JSON file) ◄──┐ │
└─────────────────────────────────────────────────┬─┘ │
                                                   │   │
┌──────────────────────────────────────────────────┼───┘
│  python -m src.polymarket (separate process)     │
│                                                  │
│  ┌──────────────┐  ┌────────────────┐            │
│  │  Phase 1     │  │  Phase 2       │            │
│  │  Scanner     │→ │  Executor      │            │
│  │  CLOB API    │  │  RiskGuard     │            │
│  └──────────────┘  └───────┬────────┘            │
│                             ↓                    │
│  ┌──────────────────────────────────┐            │
│  │  Phase 3: monitor_positions()    │            │
│  │  Checks P&L, resolves, closes   │────────────┘
│  │  Writes: data/polymarket_positions.json
│  │           logs/poly_YYYY-MM-DD.log             │
│  └──────────────────────────────────┘            │
│                                                  │
│  data/poly_paused.flag  ←→  POST /api/poly/pause │
└──────────────────────────────────────────────────┘
```

---

## Strategies

| Strategy | Description |
|---|---|
| `orderbook_spread` | Riskless arb when `YES_ask + NO_ask + fee < $1.00` |
| `cross_market` | Price discrepancy between matched Polymarket and Kalshi questions |
| `correlated_markets` | Dominance violation: P(BTC > $X) > P(BTC > $Y) where X < Y |

---

## Position lifecycle

```
open ──→ closing ──→ closed   (terminal)
     └──→ resolved            (terminal, market settled)
     └──→ stale               (terminal, requires human review)
unhedged ──→ closing ──→ closed
```

---

## Running tests

```bash
# All polymarket + dashboard tests
pytest tests/polymarket/ tests/dashboard/

# Polymarket only
pytest tests/polymarket/

# Dashboard only
pytest tests/dashboard/
```

---

## Live execution prerequisites

1. Install the optional order-placement library:
   ```bash
   pip install 'py-clob-client>=0.7'
   ```
2. Fund your Polymarket wallet with USDC on Polygon.
3. Set `POLY_DRY_RUN=false` and all four credential env vars.
4. Set a strong `DASHBOARD_API_TOKEN` before exposing the API.
5. Review the hardening checklist in the Phase 4 summary.
