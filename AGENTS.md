# AGENTS.md

## Project Overview
- This repository is a trading-system MVP for research, backtesting, analytics, and paper trading.
- Default mode is non-live: no real broker execution, no real money movement.
- Priorities, in order: safety, auditability, simplicity, reproducibility.
- Target stack: Python backend now, Next.js frontend UI later.

## Architecture Summary
- `src/data`: market data loading and normalization.
- `src/strategies`: pure signal generation (`generate_signals(data)`).
- `src/backtest`: simulation engine, transaction cost modeling, performance metrics.
- `src/risk`: position limits, loss limits, kill-switch behavior.
- `src/execution`: paper-order models/executor and trade logging; no live execution by default.
- `src/config`: typed runtime settings from environment/config files.
- `tests`: unit tests for core logic and regression protection.

## Coding Standards
- Use Python 3.12-compatible code and type hints for all public APIs.
- Add short docstrings for modules, classes, and non-trivial functions.
- Prefer explicit, readable logic over abstraction-heavy patterns.
- Keep functions small and deterministic where possible.
- Log or persist key decision points when behavior affects PnL/risk.
- Do not add dependencies unless there is clear, recurring value.

## Execution policy
- Follow `docs/codex-plan.md` for sequencing and acceptance criteria.
- Follow `docs/implement.md` for execution behavior.
- Do not pause after each step unless a pause condition in `docs/implement.md` is met.

## Execution behavior
- Follow docs/codex-plan.md as the source of truth for sequencing.
- Execute all steps in order without pausing for approval between steps.
- After each step:
  - run the relevant tests/validation
  - fix failures immediately
  - commit only if explicitly instructed
  - continue to the next step automatically
- Pause only if:
  - a required secret, credential, or external dependency is missing
  - tests fail in a way that cannot be resolved safely
  - the next step would require a broad architectural change not covered by the plan

## Testing Expectations
- Every behavior change requires tests or an explicit rationale for why tests are not needed.
- Cover success paths, edge cases, and failure paths for core modules.
- Preserve or improve test coverage for: strategy signals, backtest accounting, risk controls, execution logging.
- Backtest/risk/execution changes should include regression-style tests when possible.

## Assumptions Before Implementation
- Before writing code, state assumptions clearly and concretely.
- If assumptions materially affect behavior, confirm them first.
- If assumptions are low-risk, document them in the change summary.

## Change Scope Discipline
- Keep changes minimal and targeted to the requested task.
- Avoid opportunistic refactors in the same patch unless required for correctness.
- Preserve existing behavior unless an intentional behavior change is requested.
- If behavior is intentionally changed, document what changed, why, and expected impact.

## Rules for Strategy Modules (`src/strategies`)
- Keep strategies focused on signal generation; avoid embedding execution/risk logic.
- Define clear input/output contracts and maintain index alignment with input market data.
- Avoid look-ahead bias; only use information available at signal time.
- Strategy outputs must remain simple and testable (e.g., bounded position targets).

## Rules for Backtest Code (`src/backtest`)
- Treat accounting correctness as critical: fees, slippage, turnover, and equity updates must be explicit.
- Preserve determinism for identical inputs/configs.
- Separate simulation mechanics from reporting calculations.
- Any changes to fill timing, return calculation, or cost modeling require regression tests.

## Rules for Execution Code (`src/execution`)
- Default to paper trading stubs; do not enable live trading by default.
- Keep order/fill models explicit and serializable for audit logs.
- Persist trade/fill logs in a stable, reviewable format (CSV/structured records).
- Guard invalid order inputs with clear errors.

## Rules for Risk-Sensitive Modules (`src/risk`, risk-related config/flow)
- Prefer fail-safe behavior (flatten/block) over permissive behavior.
- Risk checks must be explicit, easy to trace, and covered by tests.
- Changes to max position sizing, loss limits, or kill-switch logic require test updates.
- Never bypass risk controls silently; if bypass is needed for research, make it explicit and opt-in.

## Live Trading Guardrails
- Live trading must remain disabled by default in code and config.
- Any live-trading pathway must be explicit, gated, and off unless intentionally enabled.
- Do not add hidden auto-connect or auto-submit behavior to real brokers.
