---
name: paper-trading-debug
description: Analyze Trauto paper-trading runs, identify root causes, and propose minimal safe fixes.
---

Use this skill after a paper-trading session or when broker/app behavior looks wrong.

Goals:
1. Reconstruct the order lifecycle from logs.
2. Identify the first concrete failure or mismatch.
3. Compare local app state with broker state.
4. Detect duplicate orders, missing fills, stale positions, or exit logic failures.
5. Propose the smallest safe fix.
6. Add or update tests when behavior changes.

Required output:
- Root cause
- Evidence from logs
- Proposed fix
- Tests added or needed
- Residual risk

Rules:
- Preserve structured logging.
- Do not weaken risk controls.
- Do not enable live trading.
- Prefer reversible fixes.