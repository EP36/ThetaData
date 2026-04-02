# Codex Build Plan — Trading System MVP

## Purpose

This file defines the ordered implementation plan for a trading-system MVP. It is intended to be used by Codex together with `AGENTS.md` and `README.md`.

This project is for:

- research
- backtesting
- analytics
- paper trading

This project is **not** for live trading by default.

## Global Rules

These rules apply to every step:

1. Inspect relevant files before making changes.
2. Summarize what will change before implementing.
3. Keep changes minimal and targeted.
4. Preserve existing behavior unless intentionally changing it.
5. Do not do broad rewrites unless absolutely necessary.
6. Prefer simple, auditable code over clever abstractions.
7. Add or update tests when behavior changes.
8. Run relevant tests after each step.
9. Update README when setup, architecture, or usage changes.
10. Never enable live trading by default.
11. Frontend must not contain trading logic.
12. Risk-sensitive modules must favor safety and explicitness.
13. If integration is not ready, use clearly isolated mock data or stub implementations.
14. Use strong typing where practical.
15. Call out assumptions, known risks, and potential sources of backtest bias.

---

## Step 1 — Create `AGENTS.md`

### Goal
Create a repo-level instruction file so future Codex work stays consistent.

### Requirements
Include:
- project overview
- architecture summary
- coding standards
- testing expectations
- rules for modifying strategy modules
- rules for modifying backtest code
- rules for modifying execution code
- rules for modifying risk-sensitive modules
- instruction to explain assumptions before implementation
- instruction to keep changes minimal
- instruction to avoid enabling live trading by default

### Acceptance Criteria
- `AGENTS.md` exists
- the rules are concise, practical, and specific to this repo
- future steps can rely on it for consistent behavior

### Validation
- confirm file exists
- confirm it reflects the repo architecture and safety constraints

---

## Step 2 — Audit the Scaffold

### Goal
Review the scaffolded repository and make the smallest safe improvements before adding features.

### Requirements
- inspect current structure and starter files
- identify weak naming, placeholder code, module boundary problems, config issues, or confusing boilerplate
- improve the scaffold without doing a broad rewrite
- ensure `requirements.txt`, `README.md`, `.env.example`, and starter tests are coherent

### Acceptance Criteria
- scaffold is internally consistent
- setup instructions are accurate
- obvious placeholder or misleading code is cleaned up
- architecture remains stable for later steps

### Validation
- run tests
- ensure project imports still work
- verify README setup instructions are still correct

---

## Step 3 — Build the Backtesting Engine

### Goal
Add a realistic but simple backtesting engine.

### Requirements
- input: OHLCV `pandas.DataFrame` indexed by timestamp
- output:
  - equity curve
  - trades list
  - summary metrics
- support:
  - long-only
  - fixed transaction fee
  - percentage slippage
  - position sizing by percent of equity
  - stop loss
  - take profit
- separate concerns:
  - signal generation
  - portfolio simulation
  - metrics
  - reporting
- keep implementation simple and testable

### Suggested Files
- `src/backtest/engine.py`
- `src/backtest/models.py`
- `src/backtest/metrics.py`
- `tests/backtest/...`

### Acceptance Criteria
- engine can consume market data and signals
- trades and equity curve are produced deterministically
- fees and slippage affect results correctly
- code integrates with current repo structure

### Validation
Add tests for:
- fill logic
- PnL calculations
- drawdown calculations
- fee/slippage impact

---

## Step 4 — Add Strategy Interface and Registry

### Goal
Create a pluggable strategy system.

### Requirements
Each strategy must expose:
- `name`
- `required_columns`
- `generate_signals(data: pd.DataFrame) -> pd.DataFrame`

Also:
- add a strategy registry
- make backtest engine consume strategies through the common interface
- validate required input columns clearly

### Suggested Files
- `src/strategies/base.py`
- `src/strategies/registry.py`
- `tests/strategies/...`

### Acceptance Criteria
- strategies can be registered and looked up by name
- backtest engine does not need strategy-specific logic
- invalid or incomplete data fails clearly

### Validation
Add tests for:
- strategy registration
- strategy loading
- required column validation

---

## Step 5 — Add Two Sample Strategies

### Goal
Add working strategies so the system can produce real outputs.

### Strategies
1. moving average crossover
2. RSI mean reversion

### Requirements
- place strategies under `src/strategies`
- expose configurable parameters
- validate required columns
- register both strategies
- ensure signal output format matches backtest engine expectations

### Suggested Files
- `src/strategies/moving_average_crossover.py`
- `src/strategies/rsi_mean_reversion.py`
- README usage section
- tests

### Acceptance Criteria
- both strategies run through the backtester
- parameters are configurable
- signal logic is test-covered
- README explains how to run them

### Validation
Add tests for:
- signal generation
- parameter handling
- edge cases with missing/short data

---

## Step 6 — Build Market Data Ingestion

### Goal
Add a structured data ingestion layer for historical market data.

### Requirements
- configurable provider interface
- normalize to columns:
  - `timestamp`
  - `open`
  - `high`
  - `low`
  - `close`
  - `volume`
- save locally as parquet
- handle missing data
- handle duplicate timestamps
- allow loading by:
  - symbol
  - timeframe
  - date range
- include retry logic
- add local cache layer
- avoid provider lock-in

### Suggested Files
- `src/data/providers/base.py`
- `src/data/providers/...`
- `src/data/cache.py`
- `src/data/loaders.py`
- `tests/data/...`

### Acceptance Criteria
- normalized OHLCV data can be fetched or stubbed and loaded consistently
- cache prevents unnecessary re-downloads
- missing/duplicate timestamp handling is explicit

### Validation
Add tests for:
- normalization
- duplicate removal or handling
- cache hits/misses
- provider interface behavior

---

## Step 7 — Add Performance Analytics

### Goal
Produce useful performance metrics and report artifacts.

### Required Metrics
- total return
- annualized return
- volatility
- Sharpe ratio
- Sortino ratio
- max drawdown
- Calmar ratio
- win rate
- average win
- average loss
- profit factor
- expectancy

### Also Generate
- equity curve plot
- drawdown plot
- monthly returns table

### Requirements
- use `matplotlib` only
- separate plotting from metric calculations
- integrate with current backtest output
- return both raw metrics and report artifact paths or objects

### Suggested Files
- `src/analytics/metrics.py`
- `src/analytics/reporting.py`
- `src/analytics/plots.py`
- `tests/analytics/...`

### Acceptance Criteria
- metrics are computed from backtest results
- chart/report output is reproducible
- modules are separate and testable

### Validation
Add tests for:
- metric correctness on known sample data
- output structure
- report generation behavior

---

## Step 8 — Add a CLI

### Goal
Provide an operator-friendly interface for core workflows.

### Commands
- `download-data`
- `backtest`
- `report`

### Requirements
- use `argparse` or `typer`
- configurable:
  - symbol
  - timeframe
  - date range
  - strategy
  - basic risk settings
- command layer must call reusable modules
- no business logic inside CLI handlers

### Suggested Files
- `src/cli/...`
- entrypoint script/module
- README examples
- tests

### Acceptance Criteria
- commands run the expected workflows
- help text is clear
- README documents usage

### Validation
Add:
- at least one integration-style CLI test
- smoke test for argument parsing

---

## Step 9 — Add Risk Engine

### Goal
Create a central risk validation layer.

### Risk Rules
- max position size as percent of equity
- max gross exposure
- max number of open positions
- max daily loss
- reject orders outside allowed trading hours
- optional stop loss
- optional trailing stop
- emergency kill switch if equity drawdown exceeds threshold

### Requirements
- encapsulate risk checks in a clear API, such as `RiskManager`
- every order request must pass through risk validation
- return structured approval or rejection reasons
- keep design auditable and simple

### Suggested Files
- `src/risk/manager.py`
- `src/risk/models.py`
- `tests/risk/...`

### Acceptance Criteria
- risk rules can be evaluated consistently
- rejection reasons are structured and understandable
- risk engine is easy to integrate with execution and backtesting

### Validation
Add tests for each rule and for combined rule evaluation.

---

## Step 10 — Add Paper Trading Executor

### Goal
Add execution simulation for paper trading only.

### Requirements
- paper trading only
- no live broker integration
- simulate order placement and fills
- track:
  - submitted orders
  - filled orders
  - canceled orders
  - positions
  - realized PnL
  - unrealized PnL
- add broker abstraction for future extensibility
- all orders must pass through the risk engine

### Safety Requirements
- trading disabled by default
- explicit `PAPER_TRADING=true` required
- max notional per trade
- max open positions
- daily loss cap
- kill switch support

### Suggested Files
- `src/execution/executor.py`
- `src/execution/broker.py`
- `src/execution/models.py`
- tests

### Acceptance Criteria
- paper executor can process simulated orders safely
- risk layer is enforced
- no live capability is introduced by default

### Validation
Add tests for:
- disabled-by-default behavior
- risk rejection path
- fill simulation
- PnL tracking
- kill switch behavior

---

## Step 11 — Add Backend API Layer

### Goal
Expose backend capabilities to a dashboard frontend.

### Endpoints
- `GET /api/dashboard/summary`
- `POST /api/backtests/run`
- `GET /api/strategies`
- `PATCH /api/strategies/:name`
- `GET /api/risk/status`
- `GET /api/trades`
- `POST /api/system/kill-switch`

### Requirements
- use a lightweight Python web framework
- keep API handlers separate from business logic
- use typed request/response schemas
- use mock or local data where full integration is not ready
- avoid introducing live trading

### Suggested Files
- `src/api/...`
- request/response models
- app bootstrap
- tests

### Acceptance Criteria
- frontend-consumable endpoints exist
- route handlers call backend modules or isolated mocks
- typed contracts are defined clearly

### Validation
Add endpoint tests for representative routes.

---

## Step 12 — Scaffold Frontend Dashboard Shell

### Goal
Create the initial Next.js dashboard frontend.

### Tech
- Next.js App Router
- TypeScript
- Tailwind CSS
- Recharts

### Pages
- `/dashboard`
- `/strategies`
- `/backtests`
- `/risk`
- `/trades`

### Dashboard Requirements
- summary cards:
  - equity
  - daily PnL
  - total PnL
  - open positions
- equity curve chart
- drawdown chart
- recent trades table
- risk alerts panel
- system status badge

### Requirements
- use mock data first
- keep components modular
- frontend must not contain trading logic

### Suggested Files
- `apps/web/...` or equivalent
- shared UI components
- mock data layer

### Acceptance Criteria
- frontend shell runs
- dashboard page renders with mock data
- page structure supports later API integration

### Validation
- run frontend locally
- ensure routes render cleanly
- basic component tests if already supported

---

## Step 13 — Build Backtests Page

### Goal
Add a page to run and review backtests.

### Requirements
Inputs:
- symbol
- timeframe
- date range
- strategy
- strategy parameters

Outputs:
- total return
- Sharpe ratio
- max drawdown
- win rate
- profit factor
- equity curve chart
- drawdown chart
- trades table

### Requirements
- use typed mock responses first
- keep data access separate from presentation
- keep styling consistent with dashboard shell

### Acceptance Criteria
- page is usable with mock data
- UI supports later real API integration
- components are reusable where practical

### Validation
- local UI run
- verify form interactions and empty/loading states

---

## Step 14 — Build Strategies Page

### Goal
Add strategy management UI.

### Requirements
For each strategy show:
- name
- description
- status
- editable parameters

Also:
- enable/disable paper trading toggle or control
- validation for parameter inputs
- typed interfaces for data

### Requirements
- mock data first
- logic separate from presentation
- no business logic in page component

### Acceptance Criteria
- strategies page renders clearly
- parameter editing is possible in the UI
- mock integration layer is isolated

### Validation
- local UI run
- verify validation and state behavior

---

## Step 15 — Build Risk Page

### Goal
Add an operational risk-monitoring UI.

### Requirements
Show:
- max daily loss
- current drawdown
- max position size
- gross exposure
- kill switch status
- rejected orders

Also:
- prominent emergency stop button
- risk events table with timestamps and reasons

### Requirements
- mock endpoint initially
- serious operational design
- keep data layer separate from components

### Acceptance Criteria
- risk state is visible in a clear operational layout
- emergency stop UI exists
- event history table is usable

### Validation
- verify rendering
- verify mock stop action flow
- verify error/loading states

---

## Step 16 — Build Trades Page

### Goal
Add a page for recent trade history.

### Requirements
Table columns:
- timestamp
- symbol
- side
- quantity
- entry price
- exit price
- realized PnL
- strategy
- status

Also add filters for:
- symbol
- strategy
- date range

### Requirements
- mock data first
- reusable filter/table components
- consistent operational styling

### Acceptance Criteria
- readable trades table exists
- filtering works on mock data
- empty/loading states are handled

### Validation
- local UI run
- verify filter behavior

---

## Step 17 — Connect Frontend to Backend

### Goal
Replace mock data with real API integration where available.

### Frontend Client Functions
- `getDashboardSummary`
- `getBacktestResults`
- `getStrategies`
- `updateStrategyConfig`
- `getRiskStatus`
- `getTrades`
- `triggerKillSwitch`

### Requirements
- typed client layer
- preserve existing page/component structure
- graceful loading/error/empty states
- keep mock fallback isolated where endpoints are missing
- frontend remains free of trading logic

### Acceptance Criteria
- pages use real backend data where supported
- contracts between frontend and backend are typed and clear
- fallback behavior is explicit and isolated

### Validation
- local frontend-backend integration works
- verify representative flows across pages

---

## Step 18 — Add Observability and Logging

### Goal
Add structured visibility into system behavior.

### Requirements
Log:
- data loads
- strategy execution
- backtest runs
- orders
- fills
- risk rejections
- kill switch events

Also:
- per-run unique ID
- logs to console and file
- useful error context
- end-of-run summary:
  - symbols processed
  - number of signals
  - number of trades
  - final equity
  - max drawdown

### Requirements
- simple implementation
- no unnecessary frameworks
- integrate cleanly with existing modules

### Acceptance Criteria
- important execution paths are logged
- logs are useful for debugging and auditability
- logging does not overly complicate the codebase

### Validation
- verify log output paths
- verify representative logged events
- ensure errors include useful context

---

## Step 19 — Add Walk-Forward Testing

### Goal
Add out-of-sample parameter evaluation support.

### Requirements
- repeated train/test windows
- parameter grid optimization on train window
- evaluate best params on following test window
- aggregate out-of-sample performance
- save parameter choices and per-window metrics

### Requirements
- avoid overengineering
- keep API simple
- document overfitting risks clearly
- integrate with existing strategy/backtest architecture

### Acceptance Criteria
- walk-forward runner works with existing strategy parameter interface
- output includes per-window metrics and aggregate results
- documentation warns about overfitting and misuse

### Validation
Add tests for:
- window generation
- aggregation
- parameter selection workflow

---

## Step 20 — Final Hardening Pass

### Goal
Audit and improve repo reliability with minimal high-leverage changes.

### Review Areas
- missing tests
- unsafe defaults
- missing env validation
- poor error handling
- hidden coupling
- bad naming
- dead code
- config drift
- reproducibility issues
- security issues around secrets
- frontend/backend contract drift
- unrealistic backtest assumptions that should be documented

### Deliverables
1. prioritized list of issues
2. minimal code changes to improve reliability
3. tests for critical paths where missing
4. README updates
5. `Known Risks` section

### Acceptance Criteria
- repo is more reliable without a broad rewrite
- key risks are documented
- critical paths have reasonable coverage

### Validation
- run relevant tests
- confirm setup still works end to end
- confirm Known Risks section exists

---

## Execution Protocol for Codex

When executing this plan:

For each step:
1. Read the step definition fully.
2. Inspect relevant files before changing anything.
3. Briefly summarize what will change.
4. Implement only the current step.
5. Run relevant tests and validations.
6. Fix issues discovered during validation.
7. Briefly summarize what changed.
8. Proceed to the next step.

Do not:
- skip steps
- enable live trading
- do broad rewrites without strong justification
- move frontend trading logic into the UI
- leave unsafe defaults in place

If a step is partially blocked:
- implement the smallest safe version
- isolate mocks/stubs clearly
- document what remains for later integration

## Autonomy Rule
Codex should execute this plan end-to-end without asking to proceed after each step.
It should only stop for:
- missing credentials or environment requirements
- irreconcilable test/build failures
- ambiguity that would create risky or broad-scope changes
Otherwise, after completing validation for the current step, it must continue to the next step automatically.