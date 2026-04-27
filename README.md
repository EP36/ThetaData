# Trauto — Unified Algorithmic Trading Platform

> **Status (April 2026):** Worker running live on Hetzner Helsinki (`ubuntu-4gb-hel1-1`). All three crypto arb strategies are scanning; no errors in logs. Opportunities are being ranked but thresholds have not been crossed yet.

Trauto is a modular **Python 3.12** algorithmic trading platform that runs three independent carry/arb strategies on a single VPS and uses a composite scoring model to rank opportunities. A new `trauto/` package (Phase 7) is being migrated in alongside the original `src/` engine — both coexist until the migration is complete.

> **Capital does not move automatically between venues.** Cross-venue rebalancing is on the roadmap — see [Roadmap](#roadmap).

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Live Strategies](#live-strategies)
  - [1. Polymarket Arbitrage](#1-polymarket-arbitrage-polymarket)
  - [2. Hyperliquid Funding-Rate Arb](#2-hyperliquid-funding-rate-arb-funding_arbmonitorpy)
  - [3. Coinbase Spot + HL Perp Basis Arb](#3-coinbase-spot--hl-perp-basis-arb-funding_arbcoinbase_clientpy)
- [Capital Flow Map](#capital-flow-map)
- [Capital Allocator](#capital-allocator-srccapitalallocatorpy)
- [What to Deposit Where](#what-to-deposit-where)
- [Configuration](#configuration-etctrautoenv)
- [Project Structure](#project-structure)
- [Phase 7 — Unified Engine](#phase-7--unified-engine-trauto)
- [Legacy Equity Strategies](#legacy-equity-paper-trading-strategies)
- [VPS Operations](#vps-operations-hetzner-helsinki)
- [Safety Defaults](#safety-defaults)
- [Roadmap](#roadmap)

---

## Architecture Overview

```
/opt/trauto   (Hetzner VPS, Helsinki)
├── trauto-worker.service  ← systemd background loop
├── trauto-web.service     ← FastAPI dashboard + API
│
├── polymarket/            ← Polymarket CLOB v2 arb
├── funding_arb/           ← Hyperliquid funding + Coinbase basis arb
│   ├── monitor.py         ← scan loop, strategy picker
│   ├── executor.py        ← HL order placement
│   └── coinbase_client.py ← CB spot price + order feed
├── src/
│   └── capital/
│       └── allocator.py   ← composite opportunity scorer (read-only)
├── trauto/                ← Phase 7 unified engine (migration in progress)
└── /etc/trauto/env        ← all secrets & config (not in repo)
```

### Worker Boot Order

1. `trauto-worker` starts, reads `/etc/trauto/env`
2. Three strategy threads start in parallel:
   - Polymarket arbitrage monitor
   - Hyperliquid funding-rate monitor (`funding_arb/monitor.py`)
   - Coinbase spot → HL perp basis monitor (`coinbase_client.py`)
3. Each cycle calls `CapitalAllocator.rank()` to score live opportunities
4. Orders are placed only when an opportunity clears the configured threshold **and** the relevant `DRY_RUN` flag is `false`

---

## Live Strategies

### 1. Polymarket Arbitrage (`polymarket/`)

| Item | Detail |
|------|--------|
| Venue | Polymarket CLOB v2 |
| Network | **Polygon** (MATIC gas, USDC.e collateral) |
| Wallet | Dedicated Polygon EOA (`POLY_WALLET`) |
| Edge | Order-book spread + correlated-market mispricing |
| Status | Scanning; CLOB v2 migration pending **April 28** |
| Dry-run flag | `POLY_DRY_RUN=true` in `/etc/trauto/env` |

**Funding this venue:**
1. Bridge USDC to Polygon (e.g. via [Stargate](https://stargate.finance) or Coinbase → Polygon)
2. Send to your `POLY_WALLET` address on Polygon
3. Approve the CLOB v2 contract once: `python3 approve_polymarket.py`
4. Polymarket locks USDC as collateral per open position — it is **not** available to other venues while deployed

---

### 2. Hyperliquid Funding-Rate Arb (`funding_arb/monitor.py`)

| Item | Detail |
|------|--------|
| Venue | Hyperliquid L1 (spot + perp) |
| Network | **Arbitrum** bridge → HL deposit |
| Wallet | HL vault wallet (`HL_WALLET`) |
| Edge | Long HL spot + short HL perp; collect hourly funding when rate > 0.15 %/hr |
| Break-even | 0.11 %/hr (round-trip maker fees: spot 0.04 % × 2 + perp 0.015 % × 2) |
| Assets scanned | BTC, ETH, SOL, HYPE, WIF, DOGE, AVAX, ONDO |
| Status | Scanning every 60 s; waiting for rate ≥ `HL_MIN_FUNDING_RATE` |
| Dry-run flag | `HL_DRY_RUN=true` in `/etc/trauto/env` |

**Funding this venue:**
1. Bridge USDC/USDT via [Hyperliquid bridge](https://app.hyperliquid.xyz/portfolio) from Arbitrum
2. Deposit lands in your HL account associated with `HL_WALLET`
3. Capital must cover **both** legs: spot buy + perp margin simultaneously
4. Rule of thumb: fund 2× the intended position size for margin buffer

---

### 3. Coinbase Spot + HL Perp Basis Arb (`funding_arb/coinbase_client.py`)

| Item | Detail |
|------|--------|
| Venues | Coinbase Advanced Trade (spot) + Hyperliquid (perp) |
| Networks | Coinbase custodial (USD/USDC) + HL vault |
| Wallets | Coinbase API key (`COINBASE_API_KEY`) + `HL_WALLET` |
| Edge | Perp mark > CB spot (contango) → sell perp short on HL, buy spot on CB; delta-neutral |
| Signal | `basis_pct × 52 weeks` as annualized proxy; threshold set by `MIN_BASIS_PCT` (default 1 %) |
| Status | Integrated; uses CB real spot price as primary, HL spot proxy as fallback |
| Dry-run flag | `BASIS_DRY_RUN=true` in `/etc/trauto/env` |

**Funding this venue:**
1. Fund your Coinbase Advanced Trade account with USD or USDC (normal ACH/wire or crypto deposit)
2. Set `COINBASE_API_KEY` and `COINBASE_API_SECRET` (EC private key PEM) in `/etc/trauto/env`
3. The HL perp leg uses the same `HL_WALLET` margin as strategy 2 — **shared capital pool on HL**
4. Size the CB deposit to match your HL available margin so both legs are balanced

---

## Capital Flow Map

```
┌─────────────────────────────────────────────────────┐
│                  YOUR CAPITAL TODAY                  │
└──────┬────────────────┬────────────────┬────────────┘
       │                │                │
       ▼                ▼                ▼
 ┌──────────┐    ┌───────────────┐  ┌──────────────┐
 │ Polygon  │    │  Arbitrum /   │  │  Coinbase    │
 │  wallet  │    │  HL vault     │  │  custodial   │
 │ (USDC.e) │    │  (USDC/USDT)  │  │  (USD/USDC)  │
 └────┬─────┘    └───────┬───────┘  └──────┬───────┘
      │                  │                 │
      ▼                  ▼                 ▼
 Polymarket         HL spot + perp     CB spot price
 CLOB v2 arb        funding arb         (feeds basis
                    (strat 2)           calc; CB spot
                    + basis arb         leg of strat 3)
                    (strat 3 perp leg)
```

### Key Constraint: Capital Is Venue-Siloed

Capital deposited to Polygon **cannot** fill a Hyperliquid opportunity without a manual bridge + withdraw. The `CapitalAllocator` ranks opportunities by composite score but **does not move capital between venues**. If HL funding arb is returning 200 % annualized and Polymarket is returning 50 %, Trauto will *prefer* the HL opportunity when sizing new trades — but Polymarket collateral locked in existing positions stays there.

---

## Capital Allocator (`src/capital/allocator.py`)

The allocator ranks `OpportunityScore` objects from all strategies and logs the top-5 each cycle.

```
Composite score = 0.40 × annualized_edge
               + 0.30 × exec_confidence
               + 0.20 × capital_efficiency
               + 0.10 × (1 − lockup_penalty)
```

**What it does today:**
- Scores and ranks opportunities cross-venue
- Blocks trades that score below a minimum threshold
- Logs rankings with `capital_rank` structured log events

**What it does NOT do today:**
- Move capital between venues automatically
- Withdraw from Polymarket and deposit to HL
- Rebalance positions across chains

See [Roadmap](#roadmap) for the planned cross-venue rebalancing module.

---

## What to Deposit Where

| If you want to run… | Deposit here | Asset | Minimum suggested |
|---------------------|--------------|-------|-------------------|
| Polymarket arb | `POLY_WALLET` on Polygon | USDC.e | $100+ per market |
| HL funding arb | HL vault (bridge from Arbitrum) | USDC | 2× target position size |
| Basis arb (CB spot) | Coinbase Advanced account | USD or USDC | Match HL perp margin |
| Basis arb (HL perp) | Same HL vault as funding arb | USDC | Shared with strat 2 |

The HL vault is shared between strategies 2 and 3. The monitor compares `funding_annual` vs `basis_annual` each cycle and takes the better trade — it will not run both on the same asset simultaneously.

---

## Configuration (`/etc/trauto/env`)

All secrets and runtime config live in `/etc/trauto/env` on the VPS — never committed to the repo. Copy `.env.example` for a full annotated template.

```bash
# --- Polymarket ---
POLY_API_KEY=...
POLY_API_SECRET=...
POLY_PASSPHRASE=...
POLY_PRIVATE_KEY=0x...
POLY_WALLET=0x...
POLY_DRY_RUN=true          # set false to place real Polymarket orders

# --- Hyperliquid funding arb ---
HL_PRIVATE_KEY=0x...
HL_WALLET=0x...
HL_MIN_FUNDING_RATE=0.0015  # 0.15%/hr minimum to flag
HL_MAX_POSITION_USD=50
HL_DRY_RUN=true             # set false to place real HL orders
HL_SCAN_INTERVAL_SEC=60

# --- Coinbase basis arb ---
COINBASE_API_KEY=organizations/xxx/apiKeys/xxx
COINBASE_API_SECRET=<EC private key PEM>
MIN_BASIS_PCT=1.0           # minimum annualized basis % to trigger
BASIS_DRY_RUN=true          # set false to place real CB orders

# --- Auth ---
AUTH_SESSION_SECRET=...     # 32+ random chars
AUTH_PASSWORD_PEPPER=...

# --- Database ---
DATABASE_URL=postgresql://...
```

---

## Project Structure

```
src/
  backtest/          ← historical backtesting engine
  capital/
    allocator.py     ← cross-strategy opportunity scorer
  strategies/        ← MA crossover, RSI, VWAP, breakout (equity)
  risk/              ← position limits, drawdown kill switch
  api.py             ← FastAPI web service
trauto/              ← Phase 7 unified engine (migration in progress)
  config/            ← layered config loader (default.json + env vars)
  core/              ← async engine, unified executor, GlobalRiskManager
  brokers/           ← BrokerInterface ABC + Alpaca / Polymarket impls
  strategies/        ← BaseStrategy + Alpaca & Polymarket wrappers
  signals/           ← BtcSignals, tuner hot-reload
  backtester/        ← BacktestRunner (delegates to src.backtest)
  dashboard/         ← FastAPI router (/api/engine/*, /api/strategies/*)
funding_arb/
  monitor.py         ← funding + basis scan loop
  executor.py        ← HL order placement
  coinbase_client.py ← Coinbase Advanced Trade integration
polymarket/          ← CLOB v2 arb logic
apps/web/            ← Next.js dashboard
deploy/
  setup.sh           ← first-time VPS provisioning
  update.sh          ← rolling deploy
data/
  engine_state.json  ← emergency stop persistence
  strategy_config.json ← per-strategy enabled/allocation/schedule
tests/
requirements.txt
.env.example
```

---

## Phase 7 — Unified Engine (`trauto/`)

The `trauto/` package is being migrated in **alongside** `src/` — old tests still run; nothing is deleted until the migration is complete.

| Layer | Package | Entry point |
|-------|---------|-------------|
| Engine | `trauto.core.engine` | `TradingEngine.start()` |
| Config | `trauto.config` | `config.get("key")` |
| Brokers | `trauto.brokers` | `BrokerInterface` |
| Strategies | `trauto.strategies` | `BaseStrategy` |
| Risk | `trauto.core.risk` | `GlobalRiskManager` |
| Signals | `trauto.signals` | `BtcSignals` |
| Backtester | `trauto.backtester` | `BacktestRunner` |
| Dashboard API | `trauto.dashboard.api` | FastAPI router |

**Key design decisions:**
- **Async throughout** — `asyncio` engine; blocking broker calls wrapped in `asyncio.to_thread()`. Tick loop targets 100 ms (10 ticks/sec).
- **Dry-run default** — `engine.dry_run=true` in `config/default.json`; must be explicitly disabled.
- **Emergency stop** — persisted to `data/engine_state.json` before any stop completes; cleared only via `POST /api/engine/start`.
- **Circuit breaker** — trips after 3 consecutive broker errors; auto-resumes after cooldown; 3 trips/hour → `manual_resume_required`.
- **Config layering** — `default.json` → `config/local.json` → env vars (env wins).

For the full architecture spec and go-live checklist, see [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Legacy: Equity Paper-Trading Strategies

The original codebase includes equity paper-trading strategies (MA crossover, RSI, VWAP, breakout) running against Alpaca or synthetic data. These live under `src/strategies/` and `src/backtest/` and are available for backtesting and research, but **are not the active production workflow**.

For the full original paper-trading documentation (API endpoints, backtest engine, Render deployment), see [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## VPS Operations (Hetzner Helsinki)

```bash
# Check service status
systemctl status trauto-worker trauto-web

# Tail live logs
journalctl -u trauto-worker -f

# Deploy updates
bash /opt/trauto/deploy/update.sh

# Edit config
nano /etc/trauto/env
systemctl restart trauto-worker
```

On startup the worker logs its outbound IP:
```
outbound_ip=65.21.x.x region=hetzner-helsinki
```
Verify this IP is not blocked by Polymarket before enabling live trading.

---

## Safety Defaults

All execution flags default to **dry-run / disabled**. To place real orders you must explicitly set the following in `/etc/trauto/env`:

| Flag | Default | Enable live |
|------|---------|-------------|
| `POLY_DRY_RUN` | `true` | `false` |
| `HL_DRY_RUN` | `true` | `false` |
| `BASIS_DRY_RUN` | `true` | `false` |
| `WORKER_DRY_RUN` | `true` | `false` |
| `LIVE_TRADING` | `false` | ⚠️ raises startup error — not supported |

---

## Roadmap

### Near-term
- [ ] **April 28** — Migrate Polymarket integration to CLOB v2 API
- [ ] Alerting (Telegram / webhook) when an opportunity clears threshold
- [ ] Dashboard widget showing live `capital_rank` scores from allocator
- [ ] Complete Phase 7 migration: retire `src/` legacy modules after `trauto/` tests go green

### Cross-venue capital unification (not yet implemented)

The current allocator ranks opportunities but does not rebalance wallets. To unlock true capital efficiency across venues, the following would need to be added:

1. **Withdrawal trigger** — when a venue's best opportunity score is significantly below the global top score (configurable gap, e.g. `∆score > 0.15`), initiate a partial or full withdrawal from the lower-scoring venue.
2. **Bridge executor** — calls the appropriate bridge (Polygon → Arbitrum for HL, or HL withdrawal → Arbitrum → Coinbase) and waits for confirmation before marking funds as available.
3. **Deposit acknowledger** — polls the destination venue API to confirm the deposit landed before allowing the allocator to size new trades there.
4. **Position unwind gating** — locked Polymarket collateral can only be withdrawn after positions are closed; the rebalancer needs to distinguish *free capital* from *locked collateral*.

**Example flow (not live):**
```
Polymarket best:   50% annualized  → score 0.42
HL funding best:  200% annualized  → score 0.81
∆ = 0.39 > threshold → trigger withdrawal from Polymarket
  1. Close/wait for Polymarket positions to expire
  2. Withdraw USDC.e from Polygon wallet
  3. Bridge to Arbitrum
  4. Deposit into HL vault
  5. Allocator now sizes HL trades with larger capital
```
