---
name: paper-trading-go-no-go
description: Check whether Trauto is safe to run in paper trading before market open.
---

Use this skill when preparing Trauto for a paper-trading session.

Goals:
1. Verify the app is in paper mode, not live mode.
2. Verify required broker credentials and data credentials are present.
3. Verify risk controls are enabled.
4. Verify structured logging is enabled for signals, orders, fills, rejects, and exits.
5. Verify duplicate-order protections and kill switch behavior are still present.
6. Summarize any blockers clearly.

Required output:
- Go / No-Go decision
- Blocking issues
- Recommended fixes
- Brief risk summary

Rules:
- Never enable live trading as part of this skill.
- Do not change trading behavior unless explicitly asked.
- Prefer minimal config and observability fixes.