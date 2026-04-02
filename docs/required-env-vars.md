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

## Not Required for Initial Paper Deployment

These are optional for MVP paper deployment:
- Alpaca credentials (`BROKER_API_KEY`, `BROKER_API_SECRET`) are placeholders and not used by default.
- `DATA_API_KEY` is optional when using synthetic/local data flow.
- Strategy/risk tuning vars (`WORKER_SYMBOL`, `WORKER_STRATEGY`, `MAX_DAILY_LOSS`, etc.) have safe defaults and can be added later.

## Notes

- For Render, keep `PAPER_TRADING=false` and `WORKER_ENABLE_TRADING=false` until verification is complete.
- To intentionally enable paper execution later, set both:
  - `PAPER_TRADING=true`
  - `WORKER_ENABLE_TRADING=true`
