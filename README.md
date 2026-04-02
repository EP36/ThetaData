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

Example creation via registry:

```python
from src.strategies import create_strategy

ma = create_strategy("moving_average_crossover", short_window=20, long_window=50)
rsi = create_strategy("rsi_mean_reversion", lookback=14, oversold=30, overbought=70)
```

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
- `POST /api/system/kill-switch`
- `GET /healthz`
- `GET /api/system/status`

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

Startup validation behavior:
- in `APP_ENV=production` or with `STRICT_ENV_VALIDATION=true`, missing required env vars fail fast with a clear startup error.
- full variable matrix: [`docs/required-env-vars.md`](docs/required-env-vars.md)

Recommended:
- `RUN_MIGRATIONS_ON_STARTUP=true`
- `STRICT_ENV_VALIDATION=true`
- `WORKER_POLL_SECONDS=60`
- `WORKER_SYMBOL=SPY`
- `WORKER_TIMEFRAME=1d`
- `WORKER_STRATEGY=moving_average_crossover`
- `WORKER_STRATEGY_PARAMS_JSON={}`

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

The frontend lives in `apps/web` and is currently mock-data first.

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

Notes:
- The UI calls the backend from the browser, so backend CORS must allow your Static Site origin.
- If you prefer no cross-origin browser calls, deploy frontend and backend behind a single origin with a proxy setup.

Routes:
- `/dashboard`
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
- Frontend uses API-first with mock fallback; if backend is unavailable, UI can still render synthetic values.
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
