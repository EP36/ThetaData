#!/usr/bin/env bash
# deploy/update.sh — pull latest code and restart services.
# Run on the Hetzner server as root.
set -euo pipefail

INSTALL_DIR="/opt/trauto"
VENV="$INSTALL_DIR/.venv"

echo "==> Pulling latest code"
git -C "$INSTALL_DIR" pull --ff-only

echo "==> Installing any new dependencies"
"$VENV/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q

echo "==> Restarting services"
systemctl restart trauto-worker trauto-web

echo "==> Service status"
systemctl is-active trauto-worker trauto-web
echo "Done. Tail logs with: journalctl -u trauto-worker -f"
