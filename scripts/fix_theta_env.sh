 #!/usr/bin/env bash
  # fix_theta_env.sh — move COINBASE_API_SECRET into a systemd drop-in override

  set -euo pipefail

  SERVICE="theta-runner"
  UNIT_FILE="/etc/systemd/system/${SERVICE}.service"
  DROPIN_DIR="/etc/systemd/system/${SERVICE}.service.d"
  VAR="COINBASE_API_SECRET"

  die() { echo "ERROR: $*" >&2; exit 1; }

  [[ "$EUID" -eq 0 ]] || die "Must be run as root"
  [[ -f "$UNIT_FILE" ]] || die "Unit file not found: $UNIT_FILE"

  # ── 1. Warning ───────────────────────────────────────────────────────────────
  echo "========================================================"
  echo "  WARNING: This script modifies systemd configuration"
  echo "  for the ${SERVICE} service."
  echo "========================================================"
  echo

  # ── 2. Show current state ────────────────────────────────────────────────────
  echo "=== $UNIT_FILE ==="
  cat "$UNIT_FILE"
  echo

  if [[ -d "$DROPIN_DIR" ]]; then
    shopt -s nullglob
    drop_ins=("$DROPIN_DIR"/*.conf)
    shopt -u nullglob
    if [[ ${#drop_ins[@]} -gt 0 ]]; then
      echo "=== Existing drop-ins under $DROPIN_DIR ==="
      for f in "${drop_ins[@]}"; do
        echo "--- $f ---"
        cat "$f"
        echo
      done
    else
      echo "(Drop-in directory $DROPIN_DIR exists but contains no .conf files)"
      echo
    fi
  else
    echo "(No drop-in directory at $DROPIN_DIR)"
    echo
  fi

  # ── 3. Instructions — do NOT touch the secret in this script ─────────────────
  cat <<'INSTRUCTIONS'
  ========================================================
    TODO: You must paste the real secret yourself.
  ========================================================

  Run this command NOW in a separate terminal:

      systemctl edit theta-runner

  An editor will open (usually nano or vi).
  Paste EXACTLY the block below, replacing the placeholder
  on the Environment= line with the real secret value:

    • Keep the entire secret on ONE line.
    • Replace every literal newline inside the PEM with the
      two-character sequence  \n  (backslash + letter n).
    • Example:
        -----BEGIN EC PRIVATE KEY-----\nMHQCAQEEI...\n-----END EC PRIVATE KEY-----

  -------- PASTE THIS INTO THE EDITOR --------
  [Service]
  EnvironmentFile=
  Environment=COINBASE_API_SECRET=REPLACE_WITH_SECRET_USING_\n_FOR_NEWLINES
  ---------------------------------------------

  Save and close the editor.

  NOTE: EnvironmentFile= (blank) clears the EnvironmentFile list
  inherited from the base unit so that /etc/trauto/env no longer
  supplies COINBASE_API_SECRET.  If other variables from that file
  are still needed by the service, add them as additional
  Environment= lines in the same override block, or re-add:
      EnvironmentFile=/etc/trauto/env
  after the blank-reset line (with COINBASE_API_SECRET removed
  from the file first).

  INSTRUCTIONS

  # ── 4. Wait for confirmation ─────────────────────────────────────────────────
  read -r -p "Have you saved the override with the real secret? [y/N] " confirm
  if [[ "${confirm,,}" != "y" ]]; then
    echo "Aborted — no changes made to the running service."
    exit 0
  fi

  # ── 5. Reload and restart ────────────────────────────────────────────────────
  echo
  echo "Running: systemctl daemon-reload"
  systemctl daemon-reload

  echo "Running: systemctl restart ${SERVICE}"
  systemctl restart "$SERVICE"

  sleep 1   # give the unit a moment to reach running state

  status=$(systemctl is-active "$SERVICE" 2>/dev/null || true)
  echo
  echo "Service status: $status"
  if [[ "$status" == "active" ]]; then
    echo "theta-runner is running."
  else
    echo "WARNING: theta-runner is not active. Check: journalctl -u ${SERVICE} -n 50"
  fi

  # ── 6. Reminder ──────────────────────────────────────────────────────────────
  cat <<REMINDER

  ========================================================
    REMINDER: Remove $VAR from /etc/trauto/env
  ========================================================
  Now that $VAR lives only in the systemd drop-in override,
  the copy in /etc/trauto/env is redundant and could silently
  supply a stale value if the override is ever missing.

  Edit /etc/trauto/env and delete the line that starts with:
      $VAR=

  Then verify with check_theta_env.sh (see usage below).
  ========================================================
  REMINDER

  ---
  Usage

  Before the fix — detect a mismatch

  chmod +x check_theta_env.sh fix_theta_env.sh

  # Run as root (needs /proc/$PID/environ access)
  ./check_theta_env.sh