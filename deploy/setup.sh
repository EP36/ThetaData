#!/usr/bin/env bash
# deploy/setup.sh — run once on a fresh Hetzner Ubuntu 22.04 server as root.
# Safe to re-run: every step is idempotent.
set -euo pipefail

REPO_URL="https://github.com/EP36/Trauto.git"
INSTALL_DIR="/opt/trauto"
ENV_FILE="/etc/trauto/env"
VENV="$INSTALL_DIR/.venv"
PYTHON="$VENV/bin/python"

echo "==> Installing system packages"
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    git curl screen \
    libpq-dev gcc

echo "==> Cloning / updating repo at $INSTALL_DIR"
if [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" pull --ff-only
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

echo "==> Creating Python virtual environment"
if [[ ! -d "$VENV" ]]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q

echo "==> Creating env file at $ENV_FILE"
mkdir -p /etc/trauto
if [[ ! -f "$ENV_FILE" ]]; then
    cat > "$ENV_FILE" <<'EOF'
# ── Database ────────────────────────────────────────────────────────────────
DATABASE_URL=postgresql://trauto_user:PASSWORD@HOST:5432/trauto

# ── App ─────────────────────────────────────────────────────────────────────
APP_ENV=production
SERVICE_NAME=trauto-web
WORKER_NAME=main-worker
PYTHON_VERSION=3.11

# ── Auth ────────────────────────────────────────────────────────────────────
AUTH_SESSION_SECRET=change-me-32-chars-minimum
AUTH_PASSWORD_PEPPER=change-me-pepper

# ── Trading modes ────────────────────────────────────────────────────────────
PAPER_TRADING=false
WORKER_ENABLE_TRADING=false
LIVE_TRADING=false
KILL_SWITCH_ON_STARTUP=false
SIGNAL_PROVIDER=synthetic
TRADING_VENUE=polymarket
ALPACA_TRADING_MODE=disabled
POLY_TRADING_MODE=dry_run

# ── Polymarket credentials ───────────────────────────────────────────────────
POLY_API_KEY=
POLY_API_SECRET=
POLY_PASSPHRASE=
POLY_PRIVATE_KEY=

# ── Polymarket scanner ───────────────────────────────────────────────────────
POLY_MIN_EDGE_PCT=1.5
POLY_MIN_VOLUME_24H=0
POLY_MAX_TRADE_USDC=500
POLY_SCAN_INTERVAL_SEC=15
POLY_DRY_RUN=true

# ── Alpaca (optional, for equities signals) ─────────────────────────────────
ALPACA_API_KEY=
ALPACA_API_SECRET=

# ── AI loop ─────────────────────────────────────────────────────────────────
AI_ANALYSIS_INTERVAL_HOURS=24
AI_MONTHLY_TOKEN_BUDGET=100000

# ── Misc ─────────────────────────────────────────────────────────────────────
RUN_MIGRATIONS_ON_STARTUP=true
WORKER_POLL_SECONDS=60
CORS_ALLOWED_ORIGINS=http://localhost:8000
EOF
    echo "   Created $ENV_FILE with placeholders."
else
    echo "   $ENV_FILE already exists — not overwritten."
fi
chmod 600 "$ENV_FILE"

echo "==> Installing systemd service files"
cp "$INSTALL_DIR/deploy/trauto-worker.service" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/trauto-web.service"    /etc/systemd/system/
systemctl daemon-reload
systemctl enable trauto-worker trauto-web

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  Setup complete.  Next steps:                                    ║"
echo "║                                                                  ║"
echo "║  1. Edit $ENV_FILE                          ║"
echo "║     Fill in DATABASE_URL, POLY_* credentials, AUTH_* secrets.   ║"
echo "║                                                                  ║"
echo "║  2. Start services:                                              ║"
echo "║       systemctl start trauto-worker trauto-web                   ║"
echo "║                                                                  ║"
echo "║  3. Check logs:                                                  ║"
echo "║       journalctl -u trauto-worker -f                            ║"
echo "║       journalctl -u trauto-web -f                               ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
