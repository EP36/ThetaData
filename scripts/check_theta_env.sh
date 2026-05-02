#!/usr/bin/env bash
  # check_theta_env.sh — compare COINBASE_API_SECRET between shell and theta-runner process

  set -euo pipefail

  ENV_FILE="/etc/trauto/env"
  SERVICE="theta-runner"
  VAR="COINBASE_API_SECRET"

  die() { echo "ERROR: $*" >&2; exit 2; }

  # ── 1. Shell hash (source env file in a subshell) ───────────────────────────
  [[ -f "$ENV_FILE" ]] || die "$ENV_FILE not found"

  shell_hash=$(
    bash --noprofile --norc -c "
      source '$ENV_FILE' 2>/dev/null
      printf '%s' \"\${$VAR:-}\"
    " | sha256sum | awk '{print \$1}'
  )

  # ── 2. Locate the running service PID ───────────────────────────────────────
  pid=$(systemctl show --property=MainPID --value "$SERVICE" 2>/dev/null || true)
  [[ -n "$pid" && "$pid" != "0" ]] \
    || die "$SERVICE is not running (MainPID=0). Start it first."
  [[ -r "/proc/$pid/environ" ]] \
    || die "Cannot read /proc/$pid/environ — are you root?"

  # ── 3. Runner hash (extract from /proc/$PID/environ, null-byte delimited) ───
  # awk splits records on the null byte so embedded newlines inside a PEM value
  # are handled correctly as part of one record.
  proc_hash=$(
    awk 'BEGIN { RS="\0"; found=0 }
         /^'"$VAR"'=/ {
           printf "%s", substr($0, index($0, "=") + 1)
           found = 1
           exit
         }
         END { exit (found ? 0 : 3) }' "/proc/$pid/environ" \
    | sha256sum | awk '{print $1}'
  ) || {
    rc=$?
    [[ $rc -eq 3 ]] && die "$VAR not found in /proc/$pid/environ — not set in runner env"
    die "awk failed reading /proc/$pid/environ (rc=$rc)"
  }

  # ── 4. Compare and report ────────────────────────────────────────────────────
  echo "Variable:    $VAR"
  echo "Service PID: $pid"
  echo "Shell hash:  $shell_hash"
  echo "Runner hash: $proc_hash"
  echo

  if [[ "$shell_hash" == "$proc_hash" ]]; then
    echo "MATCH: shell and theta-runner $VAR hashes are identical"
    exit 0
  else
    echo "MISMATCH: shell and theta-runner $VAR hashes differ"
    exit 1
  fi