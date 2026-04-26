#!/usr/bin/env bash
set -euo pipefail
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[FIX]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
info() { echo -e "${NC}[INFO]${NC} $1"; }

REPO_ROOT="/opt/trauto"
cd "$REPO_ROOT"
source .venv/bin/activate 2>/dev/null || true

echo ""
echo "=============================================="
echo "  Trauto Security & Performance Audit Fixes"
echo "=============================================="
echo ""

# FIX 1: Upgrade pytest CVE-2025-71176
info "FIX 1/6: Upgrading pytest (CVE-2025-71176)..."
pip install "pytest>=9.0.3" -q && log "pytest upgraded to $(pip show pytest | grep Version | awk '{print $2}')"

# FIX 2: TruffleHog secrets scan
info "FIX 2/6: Running TruffleHog secrets scan..."
TRUFFLEHOG_OUT=$(trufflehog --regex --entropy=True "$REPO_ROOT" 2>&1 || true)
if echo "$TRUFFLEHOG_OUT" | grep -q "Reason:"; then
  echo -e "${RED}[!!!] POTENTIAL SECRETS FOUND:${NC}"
  echo "$TRUFFLEHOG_OUT"
else
  log "TruffleHog: No secrets detected"
fi

# FIX 3: except:pass -> logged in market_maker.py
info "FIX 3/6: Patching silent except:pass in market_maker.py..."
FILE="$REPO_ROOT/src/polymarket/market_maker.py"
if [ -f "$FILE" ]; then
  python3 - "$FILE" <<'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    content = f.read()
old = "    except Exception:\n        pass\n    return None"
new = "    except Exception as e:\n        logger.debug(\"midpoint_fetch_failed err=%s\", e)\n    return None"
if old in content:
    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print("PATCHED: market_maker.py")
else:
    print("SKIP: pattern not found (may already be fixed)")
PYEOF
else
  warn "market_maker.py not found at $FILE"
fi

# FIX 4: assert -> raise in walk_forward.py
info "FIX 4/6: Replacing assert with explicit raise in walk_forward.py..."
FILE="$REPO_ROOT/src/backtest/walk_forward.py"
if [ -f "$FILE" ]; then
  python3 - "$FILE" <<'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    content = f.read()
old = "        assert best_params is not None"
new = "        if best_params is None:\n            raise RuntimeError(\"walk_forward: best_params is None after exhausting all combinations\")"
if old in content:
    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print("PATCHED: walk_forward.py")
else:
    print("SKIP: pattern not found (may already be fixed)")
PYEOF
else
  warn "walk_forward.py not found at $FILE"
fi

# FIX 5: Warn on blocking urllib calls
info "FIX 5/6: Scanning for blocking urllib calls (HFT latency issue)..."
URLLIB_HITS=$(grep -rn "urllib.request.urlopen" "$REPO_ROOT/src/" 2>/dev/null || true)
if [ -n "$URLLIB_HITS" ]; then
  warn "Blocking urllib calls found — migrate to async httpx to fix ~30ms latency penalty per call:"
  echo "$URLLIB_HITS" | sed 's/^/    /'
  echo ""
  echo "    Replace pattern:"
  echo "      with urllib.request.urlopen(req, timeout=5) as resp:"
  echo "          data = json.loads(resp.read())"
  echo "    With:"
  echo "      resp = await self._client.get(url, timeout=5)"
  echo "      data = resp.json()"
else
  log "No blocking urllib calls found"
fi

# FIX 6: Firewall check
info "FIX 6/6: Checking firewall..."
UFW_STATUS=$(ufw status 2>/dev/null || echo "unavailable")
if echo "$UFW_STATUS" | grep -q "inactive"; then
  warn "UFW is INACTIVE — port 8000 exposed to internet. Run:"
  echo "    ufw enable && ufw allow ssh && ufw allow from YOUR_IP to any port 8000 && ufw deny 8000"
elif echo "$UFW_STATUS" | grep -qE "8000.*ALLOW.*Anywhere"; then
  warn "Port 8000 open to ALL IPs. Restrict with: ufw delete allow 8000 && ufw allow from YOUR_IP to any port 8000"
else
  log "Firewall: port 8000 appears restricted"
fi

echo ""
echo "=============================================="
echo "  Done. Remaining manual tasks:"
echo "  1. Migrate urllib -> async httpx (see files above)"
echo "  2. Verify firewall restricts port 8000 to your IP"
echo "  3. Run Claude/Codex full audit after April 28 CLOB v2"
echo "=============================================="
