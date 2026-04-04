# Deployment Readiness Checklist (Render, 30-Day Paper Trading)

## Command Reference
- Build command (web + worker): `pip install -r requirements.txt`
- Web start command: `bash scripts/start_web.sh`
- Worker start command: `bash scripts/start_worker.sh`

## Required Render Services
- [ ] One Web Service (`trauto-web`)
- [ ] One Background Worker (`trauto-worker`)
- [ ] One Managed Postgres database (`trauto-postgres`)

## Required Environment Variables
- [ ] `APP_ENV=production`
- [ ] `DATABASE_URL` (from Render Postgres connection string)
- [ ] `WORKER_NAME=main-worker` (set on both web and worker)
- [ ] `STRICT_ENV_VALIDATION=true`
- [ ] `RUN_MIGRATIONS_ON_STARTUP=true`
- [ ] `PAPER_TRADING=false` by default
- [ ] `WORKER_ENABLE_TRADING=false` by default
- [ ] `LIVE_TRADING=false`
- [ ] `AUTH_SESSION_SECRET` (32+ random chars)
- [ ] `AUTH_PASSWORD_PEPPER` (32+ random chars)

## Safety
- [ ] `LIVE_TRADING=false`
- [ ] `PAPER_TRADING` explicitly set (`false` by default)
- [ ] `WORKER_ENABLE_TRADING` explicitly set (`false` by default)
- [ ] Admin user bootstrapped before opening dashboard/API access
- [ ] Kill switch endpoint tested: `POST /api/system/kill-switch`

## Infrastructure
- [ ] Managed Postgres provisioned in Render
- [ ] `DATABASE_URL` injected into web and worker services
- [ ] Web service health check points to `/healthz`
- [ ] Worker service has unique `WORKER_NAME`

## Startup and Migrations
- [ ] `RUN_MIGRATIONS_ON_STARTUP=true` set for web and worker
- [ ] `python -m src.persistence.migrate` succeeds
- [ ] Web starts with `bash scripts/start_web.sh`
- [ ] Worker starts with `bash scripts/start_worker.sh`

## Runtime Validation
- [ ] `GET /healthz` returns `status=ok` and `database=ok`
- [ ] `GET /api/system/status` returns `database_ok=true`
- [ ] Worker heartbeat appears in status payload
- [ ] Strategy configs are persisted and editable via API

## Persistence Validation
- [ ] Orders are persisted
- [ ] Fills are persisted
- [ ] Positions are persisted
- [ ] Log events are persisted
- [ ] Run history is persisted
- [ ] Strategy config is persisted

## 30-Day Operations
- [ ] Daily check of health, status, risk, and heartbeat
- [ ] Daily review of recent run failures and rejection reasons
- [ ] Alerting/manual process for kill switch activation
- [ ] End-of-run export plan for orders/fills/runs/logs
