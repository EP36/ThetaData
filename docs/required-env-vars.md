# Required Environment Variables

This file documents environment variables that are **required for startup** when either:
- `APP_ENV=production`, or
- `STRICT_ENV_VALIDATION=true`.

If any required variable is missing, startup fails with a clear `ValueError` from `DeploymentSettings.from_env()`.

## Hard Required (Startup-Enforced)

| Variable | Scope | Description | Source | Safe Default for Initial Deployment |
|---|---|---|---|---|
| `APP_ENV` | Both | Runtime environment selector used for production safety behavior. | Generate yourself | `production` on Render |
| `DATABASE_URL` | Both | SQL connection string for persistence (orders, fills, positions, run history, logs, strategy config). | Render | Use Render Postgres connection string |
| `WORKER_NAME` | Both | Worker identity used for heartbeat/status linking (`/api/system/status`). | Generate yourself | `main-worker` |
| `PAPER_TRADING` | Both | Global paper-trading mode flag. Must be explicit for unattended deployment. | Generate yourself | `false` |
| `WORKER_ENABLE_TRADING` | Worker | Enables/disables worker order loop. Worker remains idle when false. | Generate yourself | `false` |
| `LIVE_TRADING` | Both | Hard live-trading guardrail. Any true-like value is rejected at startup. | Generate yourself | `false` |
| `CORS_ALLOWED_ORIGINS` | Both (used by Web) | Comma-separated allowed browser origins for backend CORS. | Generate yourself | `https://thetadata.onrender.com` |
| `AUTH_SESSION_SECRET` | Both | Secret used to HMAC-hash bearer session tokens in DB. | Generate yourself | 32+ char random string |
| `AUTH_PASSWORD_PEPPER` | Both | Secret pepper included in password-hash verification flow. | Generate yourself | 32+ char random string |

## Not Required for Initial Paper Deployment

These are optional for MVP paper deployment:
- Alpaca market-data credentials (`ALPACA_API_KEY`, `ALPACA_API_SECRET`) are only needed when `DATA_PROVIDER=alpaca`.
- Alpaca execution base URL (`ALPACA_BASE_URL`) is optional and defaults to `https://paper-api.alpaca.markets`.
- Legacy fallback `ALPACA_SECRET_KEY` is accepted temporarily, but `ALPACA_API_SECRET` is canonical.
- `DATA_API_KEY` is optional when using synthetic/local data flow.
- Auth tuning vars (`AUTH_SESSION_TTL_MINUTES`, `AUTH_LOGIN_MAX_ATTEMPTS`, `AUTH_LOGIN_WINDOW_SECONDS`, `AUTH_LOGIN_BLOCK_SECONDS`) are optional with safe defaults.
- Admin bootstrap vars (`AUTH_BOOTSTRAP_ADMIN_ON_STARTUP`, `AUTH_BOOTSTRAP_ADMIN_EMAIL`, `AUTH_BOOTSTRAP_ADMIN_PASSWORD`) are optional and should be used only for initial setup/rotation.
- Strategy/risk tuning vars (`WORKER_SYMBOL`, `WORKER_STRATEGY`, `MAX_DAILY_LOSS`, etc.) have safe defaults and can be added later.
- Universe/selection controls (`WORKER_SYMBOLS`, `WORKER_ALLOW_MULTI_STRATEGY_PER_SYMBOL`) are optional and default to safe behavior.
- `WORKER_DRY_RUN` is optional and defaults to `true` (full worker evaluation with no order submission).
- `SELECTION_MIN_RECENT_TRADES` is optional and defaults to `5`.
- `WORKER_STARTUP_WARMUP_CYCLES` is optional and defaults to `20` to avoid permanent cold-start blocking.
- Universe scanner controls (`WORKER_UNIVERSE_MODE`, `WORKER_MAX_CANDIDATES`, `MIN_PRICE`, `MIN_AVG_VOLUME`, `MIN_RELATIVE_VOLUME`, `MAX_SPREAD_PCT`) are optional and default to deterministic safe values.

## Notes

- For Render, keep `PAPER_TRADING=false` and `WORKER_ENABLE_TRADING=false` until verification is complete.
- If you enable the worker loop before paper execution, keep `WORKER_DRY_RUN=true`.
- In production/staging, do not use wildcard CORS (`*`); startup validation rejects it.
- To intentionally enable paper execution later, set all:
  - `PAPER_TRADING=true`
  - `WORKER_ENABLE_TRADING=true`
  - `WORKER_DRY_RUN=false`
