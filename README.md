# Trading System MVP (Research + Paper Trading)

A modular Python 3.12 MVP for strategy research, backtesting, and paper-trading stubs.

## Features

- Historical market data loading (CSV) + synthetic data generator
- Provider-based historical data ingestion with parquet cache and retries
- Strategy interface with `generate_signals(data)`
- Long-only backtest engine with:
  - fixed transaction fee
  - percentage slippage
  - position sizing by percent of equity
  - stop loss and take profit
- Risk manager with:
  - max position size
  - max gross exposure
  - max open positions
  - max daily loss
  - trading-hours guard
  - drawdown kill switch
- Paper trading executor stub (live trading is disabled by default)
- Trade logging to CSV
- Performance report:
  - total return
  - Sharpe ratio
  - max drawdown
  - win rate
- Deterministic analytics + allocation layer:
  - strategy-level performance analytics (including rolling windows)
  - portfolio-level contribution/exposure analytics
  - rule-based market regime classification
  - deterministic strategy eligibility + scoring + selection
- Analytics report artifacts:
  - equity curve plot
  - drawdown plot
  - monthly returns table

## Project Structure

```
src/
  backtest/
  config/
  data/
  execution/
  risk/
  strategies/
  run_sample.py
tests/
requirements.txt
.env.example
README.md
```

## Setup (Python 3.12)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run End-to-End Sample

```bash
python -m src.run_sample
```

This runs:
1. synthetic data generation
2. moving-average crossover strategy
3. risk-managed backtest
4. trade log CSV export
5. sample paper-trade stub execution

Paper order submission is disabled by default. Set `PAPER_TRADING=true` in `.env` to allow simulated paper fills.

Output files:
- `logs/trades.csv` (backtest trades)
- `logs/paper_trades.csv` (paper executor fills)

## Strategy Usage

Available registered strategies:
- `moving_average_crossover`
- `rsi_mean_reversion`
- `breakout_momentum`
- `vwap_mean_reversion`

Example creation via registry:

```python
from src.strategies import create_strategy

ma = create_strategy("moving_average_crossover", short_window=20, long_window=50)
rsi = create_strategy("rsi_mean_reversion", lookback=14, oversold=30, overbought=70)
breakout = create_strategy(
    "breakout_momentum",
    lookback_period=20,
    breakout_threshold=1.01,
    volume_multiplier=1.5,
    stop_loss_pct=0.02,
    take_profit_pct=0.05,
    trailing_stop_pct=0.02,
)
vwap = create_strategy(
    "vwap_mean_reversion",
    vwap_window=20,
    vwap_deviation=0.02,
    rsi_oversold=30,
    rsi_overbought=70,
    stop_loss_pct=0.015,
    target="vwap",
)
```

Default profiles implemented:
- `breakout_momentum`: lookback `20`, breakout threshold `1.01`, volume multiplier `1.5`, stop loss `2%`, take profit `5%`, trailing stop `2%`.
- `vwap_mean_reversion`: VWAP deviation `2%`, RSI thresholds `30/70`, stop loss `1.5%`, target `VWAP`.

## Run Tests

```bash
python -m pytest -q
```

## CLI

Use the CLI entrypoint:

```bash
python -m src.cli --help
```

Core commands:

```bash
python -m src.cli download-data --symbol SPY --timeframe 1d --force-refresh
python -m src.cli backtest --symbol SPY --timeframe 1d --strategy moving_average_crossover
python -m src.cli report --symbol SPY --timeframe 1d --strategy moving_average_crossover
```

## Backend API

Run the API locally:

```bash
python -m src.api
```

Core endpoints:
- `GET /api/dashboard/summary`
- `POST /api/backtests/run`
- `GET /api/strategies`
- `PATCH /api/strategies/{name}`
- `GET /api/risk/status`
- `GET /api/trades`
- `GET /api/analytics/strategies`
- `GET /api/analytics/portfolio`
- `GET /api/analytics/context`
- `GET /api/selection/status`
- `GET /api/worker/execution-status`
- `POST /api/system/kill-switch`
- `GET /healthz`
- `GET /api/system/status`

### Analytics Metrics

Strategy analytics (`/api/analytics/strategies`) include:
- total return
- win rate
- average win / average loss
- profit factor
- expectancy
- Sharpe ratio
- max drawdown
- trade count
- average hold time
- rolling 20-trade metrics (win rate, expectancy, Sharpe)
- recent windows (last 5 / 20 / 60 trades)

Portfolio analytics (`/api/analytics/portfolio`) include:
- equity curve
- daily pnl
- realized + unrealized pnl
- rolling drawdown
- contribution by strategy
- exposure by symbol
- open risk summary

Context analytics (`/api/analytics/context`) include:
- performance by symbol
- performance by timeframe
- performance by weekday
- performance by hour
- performance by regime

If data is insufficient, analytics endpoints return empty arrays/zero-safe values (no fake demo metrics).

### Deterministic Strategy Selection

The worker uses a deterministic `StrategySelector` (rule-based, no ML) and does **not** trade all strategies equally.

Selection flow:
1. Build current market regime (`trending`, `mean_reverting`, `neutral`) from:
   - moving-average slope
   - price vs moving average
   - ATR%
   - directional persistence
2. Apply eligibility gates per strategy:
   - strategy enabled
   - kill switch off
   - paper/worker trading gates enabled
   - sufficient recent trades/performance
   - drawdown under threshold
   - risk budget available
   - required data available
   - open-position constraints not breached
   - regime compatibility
3. Score eligible strategies with:
   - recent expectancy (35%)
   - recent Sharpe (25%)
   - win rate (15%)
   - regime fit (15%)
   - drawdown penalty (10%)
4. Select the highest-scoring strategy (default top-1).
5. Apply size reduction when score is mediocre; if no strategy clears threshold, no trade is placed.

Selection diagnostics are exposed via `/api/selection/status`, including:
- current regime and regime signals
- candidate scores
- selected strategy
- rejection reasons for non-selected strategies
- sizing/allocation decision

### Worker Execution Model (Universe + Conflict Rules)

Universe source of truth:
- `WORKER_SYMBOLS` (comma-separated) provides the explicit candidate universe.
- If `WORKER_SYMBOLS` is blank, fallback is `WORKER_SYMBOL` (single-symbol compatibility mode).
- `WORKER_UNIVERSE_MODE` controls shortlist behavior:
  - `static`
  - `top_gainers`
  - `top_losers`
  - `high_relative_volume`
  - `index_constituents` (uses explicit `WORKER_SYMBOLS` as deterministic constituent input)
- Scanner applies deterministic filters before strategy evaluation:
  - `MIN_PRICE`
  - `MIN_AVG_VOLUME`
  - `MIN_RELATIVE_VOLUME`
  - `MAX_SPREAD_PCT` (only when quote columns exist)
  - stale intraday-data exclusion
- `WORKER_MAX_CANDIDATES` limits shortlist size for each worker cycle.
- Default behavior is paper-only and non-executing until both `PAPER_TRADING=true` and `WORKER_ENABLE_TRADING=true`.

Cycle behavior:
1. Worker scans the configured symbol universe.
2. Scanner filters/ranks symbols and produces a deterministic shortlist.
3. Only shortlisted symbols are evaluated by enabled strategies.
4. For each shortlisted symbol, one strategy is selected (or none) by the selector.
5. Orders are generated only from the selected strategy outcome.

Multiple enabled strategies:
- Enabled strategies are **eligible candidates**, not auto-executed orders.
- The selector chooses one strategy per symbol decision context.
- Rejected/deprioritized strategies include explicit reasons in logs and API payloads.

Same-symbol conflict prevention:
- By default, only one strategy can actively manage an open position per symbol.
- The worker persists a per-symbol active strategy lock and blocks other strategies with reason:
  - `symbol_locked_by_active_strategy:<strategy>`
- Lock is released when the symbol position is fully closed.
- Override is explicit: `WORKER_ALLOW_MULTI_STRATEGY_PER_SYMBOL=true`.

Operational visibility:
- `GET /api/worker/execution-status` returns:
  - universe mode
  - configured universe symbols
  - scanned symbols
  - shortlisted symbols
  - selected symbol + strategy summary
  - symbol-level filter reasons
  - per-symbol active strategy lock
  - latest per-symbol action/order status
  - rejected/skipped strategy reasons from the latest decision

Universe mode examples:
```bash
# 1) Static watchlist
WORKER_UNIVERSE_MODE=static
WORKER_SYMBOLS=SPY,QQQ,AAPL,MSFT

# 2) Top gainers/losers from configured universe
WORKER_UNIVERSE_MODE=top_gainers
# or: WORKER_UNIVERSE_MODE=top_losers
WORKER_SYMBOLS=SPY,QQQ,NVDA,TSLA,AMD,AAPL,META,AMZN,MSFT,GOOGL
WORKER_MAX_CANDIDATES=5

# 3) High relative volume mode
WORKER_UNIVERSE_MODE=high_relative_volume
WORKER_SYMBOLS=SPY,QQQ,NVDA,TSLA,AMD,AAPL,META,AMZN,MSFT,GOOGL
MIN_RELATIVE_VOLUME=1.5
WORKER_MAX_CANDIDATES=5
```

### Why a Strategy Can Be Blocked While Enabled

Even when a strategy is enabled, it can still be blocked for safety/quality reasons such as:
- kill switch enabled
- paper trading disabled
- worker trading gate disabled
- no active signal
- insufficient recent trades
- recent expectancy below threshold
- recent drawdown above threshold
- insufficient risk budget
- max open positions breached
- required market data missing
- regime incompatibility
- score below threshold

### Backtest Data Source

`POST /api/backtests/run` executes the real backend backtest engine and uses the
request payload inputs directly:
- `symbol`
- `timeframe`
- `start`
- `end`
- `strategy`

Historical data is loaded through `HistoricalDataLoader` and a provider interface.

Provider selection:
- `DATA_PROVIDER=synthetic` (default, deterministic synthetic OHLCV)
- `DATA_PROVIDER=alpaca` (real historical bars from Alpaca data API)

For Alpaca mode, set:
- `ALPACA_API_KEY` and `ALPACA_API_SECRET`
- optional: `ALPACA_DATA_BASE_URL` and `ALPACA_DATA_FEED` (default `iex`)

Web service environment required for real backtests (`POST /api/backtests/run`):
- `DATA_PROVIDER=alpaca`
- `ALPACA_API_KEY=<your_alpaca_key>`
- `ALPACA_API_SECRET=<your_alpaca_secret>`
- optional: `ALPACA_DATA_BASE_URL=https://data.alpaca.markets`
- optional: `ALPACA_DATA_FEED=iex`

If Alpaca credentials are missing while `DATA_PROVIDER=alpaca`, the endpoint returns a clear `422` explaining which web-service env vars are required.

Current timeframe support in Alpaca mode:
- `1m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `1d`

Limitations:
- Alpaca data availability depends on account/feed and market hours.
- If data is unavailable for a symbol/date range, the endpoint returns an error instead of synthetic substitution.

Backtest risk + sizing defaults:
- `risk_per_trade = 1%` of account equity
- `position_size_pct = risk_per_trade_pct / stop_loss_pct`
- hard cap `max_position_size = 25%`
- hard cap `max_open_positions = 3`
- orders violating risk checks are rejected and logged

### Environment Contract: Market Data vs Execution

Canonical market-data env vars:
- `ALPACA_API_KEY`
- `ALPACA_API_SECRET`
- `ALPACA_DATA_BASE_URL`
- `ALPACA_DATA_FEED`

Canonical execution env vars:
- `ALPACA_API_KEY`
- `ALPACA_API_SECRET`
- `ALPACA_BASE_URL`

Current behavior:
- Execution is still paper-only (`PaperTradingExecutor` + `SimulatedPaperBroker`).
- `ALPACA_BASE_URL` is now part of the canonical execution config contract and is loaded by runtime settings for worker/web services.
- No live trading path is enabled by default.

Backward compatibility:
- `ALPACA_SECRET_KEY` is accepted as a temporary fallback for `ALPACA_API_SECRET`.
- Canonical name remains `ALPACA_API_SECRET`; prefer it in all new deployments.

### Web Service vs Worker Service Alpaca Env Table

| Env Var | Web Service | Worker Service | Notes |
|---|---|---|---|
| `ALPACA_API_KEY` | Required if `DATA_PROVIDER=alpaca` | Required if `DATA_PROVIDER=alpaca` | Shared Alpaca credential |
| `ALPACA_API_SECRET` | Required if `DATA_PROVIDER=alpaca` | Required if `DATA_PROVIDER=alpaca` | Shared Alpaca credential |
| `ALPACA_DATA_BASE_URL` | Optional | Optional | Default: `https://data.alpaca.markets` |
| `ALPACA_DATA_FEED` | Optional | Optional | Default: `iex` |
| `ALPACA_BASE_URL` | Optional (recommended for parity) | Recommended | Canonical execution base URL, default `https://paper-api.alpaca.markets` |
| `ALPACA_SECRET_KEY` | Optional (legacy only) | Optional (legacy only) | Deprecated fallback alias for `ALPACA_API_SECRET` |

Full contract reference: [`docs/alpaca-env-contract.md`](docs/alpaca-env-contract.md)

## Render Deployment (Web + Worker + Postgres)

This repository includes a Render blueprint at `render.yaml` for:
- Render Web Service (`theta-web`) running FastAPI
- Render Background Worker (`theta-worker`) running the unattended paper loop
- Render Managed Postgres (`theta-postgres`) for persistence

Deployment commands:

```bash
# build (both services)
pip install -r requirements.txt

# web
bash scripts/start_web.sh

# worker
bash scripts/start_worker.sh
```

Migration flow:
- `python -m src.persistence.migrate` creates/updates DB tables (create-all MVP flow).
- Startup scripts run migrations automatically when `RUN_MIGRATIONS_ON_STARTUP=true`.

Persistence coverage:
- orders
- fills
- positions
- log events
- run history
- strategy config
- worker heartbeat
- global kill-switch state

### Required Environment Variables

Minimum for Render:
- `APP_ENV=production`
- `DATABASE_URL` (Render-managed Postgres connection string)
- `WORKER_NAME` (for heartbeat and worker identity)
- `PAPER_TRADING` (`false` by default)
- `WORKER_ENABLE_TRADING` (`false` by default)
- `LIVE_TRADING=false` (must remain false)
- `CORS_ALLOWED_ORIGINS=https://thetadata.onrender.com` (comma-separated list supported)

Startup validation behavior:
- in `APP_ENV=production` or with `STRICT_ENV_VALIDATION=true`, missing required env vars fail fast with a clear startup error.
- full variable matrix: [`docs/required-env-vars.md`](docs/required-env-vars.md)

Recommended:
- `RUN_MIGRATIONS_ON_STARTUP=true`
- `STRICT_ENV_VALIDATION=true`
- `WORKER_POLL_SECONDS=60`
- `WORKER_SYMBOL=SPY`
- `WORKER_UNIVERSE_MODE=static`
- `WORKER_MAX_CANDIDATES=10`
- `WORKER_TIMEFRAME=1d`
- `WORKER_STRATEGY=moving_average_crossover`
- `WORKER_STRATEGY_PARAMS_JSON={}`
- `WORKER_SYMBOLS=SPY,QQQ`
- `WORKER_ALLOW_MULTI_STRATEGY_PER_SYMBOL=false`
- `MIN_PRICE=1.0`
- `MIN_AVG_VOLUME=100000`
- `MIN_RELATIVE_VOLUME=0.0`
- `MAX_SPREAD_PCT=1.0`

### Worker and Web Separation

- Web service responsibilities:
  - API endpoints
  - health/status checks
  - strategy config updates
  - kill switch controls
- Worker responsibilities:
  - continuous signal evaluation loop
  - risk-validated paper orders only
  - durable persistence of execution artifacts
  - heartbeat and run-history updates
- Frontend remains presentation-only and does not contain trading logic.

### Paper-Trading Safety Defaults

- `PAPER_TRADING=false` by default.
- Worker trading is blocked unless `WORKER_ENABLE_TRADING=true`.
- Worker trading requires `PAPER_TRADING=true` and respects global kill switch.
- Any `LIVE_TRADING=true` setting raises a startup validation error.

### 30-Day Unattended Runbook

1. Provision Render services using `render.yaml`.
2. Confirm web health: `GET /healthz` returns `status=ok` and `database=ok`.
3. Confirm system status: `GET /api/system/status` shows worker heartbeat.
4. Keep `PAPER_TRADING=false` and `WORKER_ENABLE_TRADING=false` for initial verification.
5. Enable paper mode intentionally:
   - set `PAPER_TRADING=true`
   - set `WORKER_ENABLE_TRADING=true`
6. Monitor daily:
   - run history in `/api/system/status`
   - risk endpoint `GET /api/risk/status`
   - log events persisted in `log_events`
7. If risk anomaly occurs:
   - trigger `POST /api/system/kill-switch` with `{"enabled": true}`
   - verify worker heartbeat status changes to paused
8. For deployments or config changes:
   - keep worker enabled only after web health is green and migrations complete
9. At day 30:
   - export run history, orders, fills, and log events for review
   - disable worker trading if extended monitoring is not required

Deployment checklist:
- See [`docs/deployment-checklist.md`](docs/deployment-checklist.md).

## Frontend (Dashboard Shell)

The frontend lives in `apps/web` and is API-first.
Demo/mock values are disabled by default and only load when explicitly enabled.

```bash
cd apps/web
npm install
cp .env.example .env.local
npm run dev
```

### Recommended Frontend Deployment: Render Static Site

`apps/web` supports static export and can be deployed as a Render Static Site.

Render settings:
- Root Directory: `apps/web`
- Build Command: `npm ci && npm run build`
- Publish Directory: `out`

Required frontend env var:
- `NEXT_PUBLIC_API_BASE_URL`:
  - local example: `http://127.0.0.1:8000`
  - Render example: `https://<your-backend-service>.onrender.com`

Optional frontend env var:
- `NEXT_PUBLIC_DEMO_MODE=false` (recommended):
  - keep `false` (or unset) in production so UI shows persisted backend data only
  - set `true` only for explicit demo/development scenarios where synthetic UI data is desired

Backtests page behavior:
- In normal mode (`NEXT_PUBLIC_DEMO_MODE=false`), backtest results come only from backend `POST /api/backtests/run`.
- When backend execution/data fails, the page shows an error state (no fake results).
- Demo backtest results are available only when `NEXT_PUBLIC_DEMO_MODE=true`.

Notes:
- The UI calls the backend from the browser, so backend CORS must allow your Static Site origin.
- Backend CORS is environment-driven via `CORS_ALLOWED_ORIGINS` (for example: `https://thetadata.onrender.com`).
- Do not use `*` in production/staging CORS config; startup validation rejects wildcard origins.
- If you prefer no cross-origin browser calls, deploy frontend and backend behind a single origin with a proxy setup.

Routes:
- `/dashboard`
- `/analytics`
- `/backtests`
- `/strategies`
- `/risk`
- `/trades`

## Notes

- The system is intentionally simple but production-oriented in structure.
- Risk management and execution are explicit modules so they can be replaced with live integrations later.
- `.env` broker values are placeholders; the sample runner remains paper-only.
- Data ingestion uses a provider interface with local parquet caching to avoid provider lock-in.

## Observability

- Runtime logs stream to console and `logs/system.log`.
- Backtest/data/execution/risk flows log structured events with a per-run `run_id`.
- Backtest completion logs include: symbol, signal count, trade count, final equity, and max drawdown.

## Walk-Forward Testing

The backtest package includes a simple walk-forward runner (`src.backtest.walk_forward.WalkForwardRunner`) for:
- rolling train/test windows
- grid search on train windows
- out-of-sample evaluation on the following test windows

Overfitting caution:
- walk-forward results can still overfit if the parameter grid is too wide or repeatedly tuned.
- treat out-of-sample metrics as sanity checks, not deployment-grade proof.
- keep parameter grids small, test realistic costs/slippage, and prefer stable performance over peak metrics.

## Known Risks

- Backtest realism is limited:
  - no market impact model
  - simplified fill assumptions
  - no partial-fill depth/latency model
- Data provider layer defaults to synthetic/local patterns unless a real provider is implemented and configured.
- Real historical backtest mode is available via `DATA_PROVIDER=alpaca` and Alpaca credentials.
- Frontend demo data is controlled by `NEXT_PUBLIC_DEMO_MODE`; keep it false in production.
- No authentication/authorization on API endpoints yet (acceptable for local MVP, unsafe for exposed deployments).
- Frontend dependency maintenance:
  - keep `apps/web` dependencies patched regularly, especially Next.js security advisories.
- Worker loop assumptions are intentionally simple:
  - one-cycle-at-a-time signal evaluation
  - synthetic provider defaults unless replaced
  - no broker latency or partial-fill simulation
- Migration strategy is create-all for MVP:
  - safe for initial deployment
  - not a replacement for versioned migrations in larger production systems
