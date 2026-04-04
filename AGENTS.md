# AGENTS.md

## Project Overview

* This repository is Trauto, a trading-system MVP for research, backtesting, analytics, paper trading, and eventually gated live trading.
* Default mode is safe/non-live. Real-money trading must remain disabled unless explicitly enabled and validated.
* Supported environments must be treated as distinct modes: backtest, paper broker, and live broker.
* Priorities, in order: safety, auditability, correctness, simplicity, reproducibility.
* Target stack: Python backend now, Next.js frontend UI later.

---

## Environment Modes

* `backtest`: historical simulation only; no broker connectivity.
* `paper`: real broker paper environment allowed; no real money movement.
* `live`: real broker execution; must remain disabled by default and require explicit opt-in.

Rules:

* Never assume behavior is identical across modes.
* Execution, fills, and timing may differ between backtest and paper/live.
* Changes affecting execution or timing must consider all modes.

---

## Architecture Summary

* `src/data`: market data loading and normalization.
* `src/strategies`: pure signal generation (`generate_signals(data)`).
* `src/backtest`: simulation engine, transaction cost modeling, performance metrics.
* `src/risk`: position limits, loss limits, kill-switch behavior.
* `src/execution`: paper-order models/executor and broker integration.
* `src/config`: typed runtime settings from environment/config files.
* `tests`: unit tests for core logic and regression protection.

---

## Coding Standards

* Use Python 3.12-compatible code and type hints for all public APIs.
* Add short docstrings for modules, classes, and non-trivial functions.
* Prefer explicit, readable logic over abstraction-heavy patterns.
* Keep functions small and deterministic where possible.
* Log or persist key decision points when behavior affects PnL/risk.
* Do not add dependencies unless there is clear, recurring value.

---

## Execution Policy

* Follow `docs/codex-plan.md` for sequencing and acceptance criteria.
* Follow `docs/implement.md` for execution behavior.
* Execute steps sequentially without unnecessary pauses.
* Slow down and be explicit when modifying execution, risk, config, or broker integration.

Pause only if:

* a required secret, credential, or external dependency is missing
* tests fail in a way that cannot be resolved safely
* the next step would require a broad architectural change not covered by the plan

---

## Observability and Auditability

* Trading behavior must be explainable from logs alone.
* Persist structured logs for:

  * signal evaluation
  * trade candidate creation
  * risk checks
  * order submission payloads
  * broker responses
  * fills / cancels / rejects
  * position open/close events
  * kill-switch activation

Rules:

* Do not remove or weaken logs in execution- or risk-sensitive paths.
* Prefer structured (machine-readable) logs for post-run analysis.
* Logs must allow reconstruction of “why a trade happened.”

---

## Broker State Reconciliation

* Local app state must be reconcilable with broker state after every session.
* Persist broker order IDs and map them to local records.
* Do not assume local state is authoritative when broker data is available.
* Prevent duplicate order submission across retries, refreshes, or restarts.

---

## Testing Expectations

* Every behavior change requires tests or a clear rationale.
* Cover:

  * success paths
  * edge cases
  * failure paths
* Preserve or improve coverage for:

  * strategy signals
  * backtest accounting
  * risk controls
  * execution + logging
* Execution/risk changes should include regression-style tests.

---

## Assumptions Before Implementation

* State assumptions clearly before coding.
* If assumptions affect trading behavior, confirm or document them.
* Low-risk assumptions should still be documented in summaries.

---

## Change Scope Discipline

* Keep changes minimal and targeted.
* Avoid unrelated refactors.
* Preserve existing behavior unless change is intentional.
* Document:

  * what changed
  * why
  * expected impact

---

## Sensitive Areas

High-risk modules require extra care, tests, and clear summaries:

* `src/execution`
* `src/risk`
* `src/backtest`
* `src/config`
* environment variable handling (paper vs live)
* scheduling / job runners / cron logic

Lower-risk:

* UI
* documentation
* analytics/reporting that does not affect decisions

---

## Rules for Strategy Modules (`src/strategies`)

* Only generate signals; no execution or risk logic.
* Avoid look-ahead bias.
* Maintain clear input/output contracts.
* Keep outputs simple and testable.

---

## Rules for Backtest Code (`src/backtest`)

* Accounting correctness is critical:

  * fees
  * slippage
  * equity updates
* Maintain determinism.
* Separate simulation from reporting.
* Changes require regression tests.

---

## Rules for Execution Code (`src/execution`)

* Default to safe modes; live trading must not be enabled by default.
* Paper broker integrations are allowed and encouraged for validation.
* Persist:

  * order IDs
  * fills
  * broker responses
* Prevent duplicate orders.
* Validate inputs strictly before sending orders.

---

## Rules for Risk Modules (`src/risk`)

* Prefer fail-safe behavior (flatten/block).
* Never silently bypass risk controls.
* Changes to limits require test updates.
* Risk logic must be easy to trace from logs.

---

## Live Trading Guardrails

* Live trading must be:

  * explicitly enabled
  * clearly gated
  * never default
* No hidden auto-execution behavior.
* Any live-trading pathway must be auditable and intentional.

---

## Acceptance Criteria for Trading-Sensitive Changes

For changes affecting strategy, execution, broker integration, or risk:

* Add or update tests
* Preserve or improve logs
* Document assumptions
* Summarize behavior changes
* Identify remaining risks
* Avoid hidden side effects

---

## Codex Autonomy Rules

* Codex may propose improvements, but trading-sensitive changes must remain reviewable.
* Do not silently modify:

  * live trading behavior
  * broker credential flows
  * risk thresholds
* Prefer small, reversible changes.
* Optimize for safety and traceability over performance.

---

## Guiding Principle

Trauto is a system for **correct, repeatable execution of trading strategies**.

Correctness and safety always take priority over speed, optimization, or feature expansion.
