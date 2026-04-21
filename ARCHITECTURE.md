<!--
=============================================================================
TRAUTO ARCHITECTURE — UNIFIED ALGORITHMIC TRADING PLATFORM
=============================================================================

Written: 2026-04-20
Phase: 7 — core engine + multi-broker platform
Status: Active migration plan

=============================================================================
CODEBASE MAP (prior to migration)
=============================================================================

CATEGORY: core / Alpaca engine
  src/worker/service.py      — main polling loop, strategy dispatch, order gen
  src/execution/executor.py  — PaperTradingExecutor (positions, P&L)
  src/execution/broker.py    — PaperBroker ABC + SimulatedPaperBroker
  src/execution/models.py    — Order, Fill, Position dataclasses
  src/risk/manager.py        — RiskManager (per-order + daily-loss checks)
  src/risk/models.py         — OrderRiskRequest, PortfolioRiskState, RiskDecision
  src/trading/gating.py      — GatedTradeIntent, gate_trade_intent()
  src/trading/session.py     — SessionContext, trading hours
  src/trading/sizing.py      — calculate_position_size()
  src/trading/types.py       — TradeIntent, TradingRiskState
  src/trading/risk_policy.py — RiskPolicyConfig, evaluate_risk_policy()
  src/trading/strategy_filters.py — StrategyFilterConfig, evaluate_strategy_filters()
  src/trading/regime.py      — MarketRegimeEvaluation, get_market_regime()

CATEGORY: Alpaca strategies
  src/strategies/base.py                   — Strategy ABC (generate_signals only)
  src/strategies/moving_average_crossover.py — MACrossover
  src/strategies/moving_average.py         — MovingAverageStrategy
  src/strategies/rsi_mean_reversion.py     — RSI mean reversion
  src/strategies/vwap_mean_reversion.py    — VWAP mean reversion
  src/strategies/breakout_momentum.py      — Breakout momentum
  src/strategies/intraday.py               — Intraday variants
  src/strategies/registry.py              — create_strategy(), list_strategies()

CATEGORY: Polymarket (Phases 1-6)
  src/polymarket/client.py        — ClobClient (HTTP, HMAC auth)
  src/polymarket/config.py        — PolymarketConfig (env-driven)
  src/polymarket/scanner.py       — fetch_btc_markets(), fetch_market_orderbooks()
  src/polymarket/opportunities.py — 3 arb scanners + Opportunity dataclass
  src/polymarket/executor.py      — execute() + ExecutionResult
  src/polymarket/positions.py     — PositionsLedger, PositionRecord
  src/polymarket/monitor.py       — monitor_positions(), check_resolution()
  src/polymarket/risk.py          — RiskGuard (poly-specific)
  src/polymarket/runner.py        — scan(), scan_and_execute()
  src/polymarket/alpaca_signals.py — BtcSignals, fetch_btc_signals()
  src/polymarket/signals.py       — score_opportunity(), classify_direction()
  src/polymarket/feedback.py      — load_feedback_records(), FeedbackRecord
  src/polymarket/tuner.py         — propose_tuning(), apply_proposal()
  src/polymarket/backtest.py      — CLI backtest script
  src/polymarket/__main__.py      — standalone scanner entrypoint

CATEGORY: dashboard / API
  src/dashboard/aggregator.py    — DashboardAggregator (Alpaca + Poly unified)
  src/dashboard/api.py           — FastAPI router (poly dashboard + tuner)
  src/api/app.py                 — Full FastAPI app (auth, strategies, backtests)
  src/api/services.py            — TradingApiService
  src/api/schemas.py             — Pydantic schemas

CATEGORY: config
  src/config/settings.py         — Settings.from_env() (Alpaca-focused)
  src/config/alpaca.py           — Alpaca credential readers
  src/config/deployment.py       — DeploymentSettings (app-level)

CATEGORY: data / persistence
  src/data/providers/            — MarketDataProvider ABC + Alpaca + Synthetic
  src/data/cache.py              — DataCache (parquet-based)
  src/data/loaders.py            — HistoricalDataLoader
  src/persistence/               — SQLite via SQLAlchemy (portfolio snapshots)

CATEGORY: analytics / backtest
  src/analytics/                 — performance_layer, metrics, plots, reporting
  src/backtest/engine.py         — BacktestEngine (long-only, paper)
  src/backtest/reporting.py      — build_summary_metrics()
  src/backtest/walk_forward.py   — Walk-forward validation

CATEGORY: auth
  src/auth/                      — JWT sessions, bcrypt, rate limiting, admin

CATEGORY: observability
  src/observability/logging.py   — configure_logging(), structlog pattern

CATEGORY: tests
  tests/                         — pytest, mirrors src/ structure

CATEGORY: runtime data
  data/polymarket_positions.json — Phase 3 ledger
  polymarket/signal_params.json  — Phase 6 params
  data/trauto.db                 — SQLite (Alpaca positions)

=============================================================================
COUPLING AND DUPLICATION INVENTORY
=============================================================================

1. TWO risk systems: src/risk/manager.py (Alpaca) + src/polymarket/risk.py (Poly)
   → New: trauto/core/risk.py unifies both behind GlobalRiskManager

2. TWO config systems: Settings.from_env() + PolymarketConfig.from_env()
   → New: trauto/config/ unified JSON + env-var layered config

3. TWO executor concepts: PaperTradingExecutor + src/polymarket/executor.py execute()
   → New: trauto/core/executor.py UnifiedExecutor delegates to broker impls

4. BTC signals coupled to polymarket: src/polymarket/alpaca_signals.py
   → New: trauto/signals/btc_signals.py (platform-level, not poly-specific)

5. Dashboard aggregator tightly coupled to PolymarketConfig constructor
   → New: trauto/dashboard/ uses unified config instead

6. Worker loop (src/worker/service.py) is sync, single-strategy-at-a-time
   → New: trauto/core/engine.py is async, multi-strategy

=============================================================================
NEW DIRECTORY STRUCTURE
=============================================================================

trauto/                          ← new top-level package (alongside src/)
  __init__.py
  config/
    __init__.py                  ← TConfig — layered config loader
    default.json                 ← all defaults, committed
    local.json                   ← gitignored overrides
  core/
    __init__.py
    engine.py                    ← async engine, main tick loop
    executor.py                  ← unified order executor (delegates to brokers)
    risk.py                      ← GlobalRiskManager, circuit breaker, e-stop
    portfolio.py                 ← combined portfolio state (all brokers)
    event_bus.py                 ← asyncio pub/sub
    scheduler.py                 ← per-strategy scheduling (always/interval/cron)
    clock.py                     ← market hours, is_market_open()
  brokers/
    __init__.py
    base.py                      ← BrokerInterface ABC
    alpaca_broker.py             ← wraps src.execution + src.data.providers.alpaca
    polymarket_broker.py         ← wraps src.polymarket.client
  strategies/
    __init__.py
    base.py                      ← BaseStrategy (on_tick, on_bar, get_signals)
    alpaca/
      __init__.py
      momentum.py                ← wraps MovingAverageCrossoverStrategy
      mean_revert.py             ← scaffold (wraps RSIMeanReversionStrategy)
    polymarket/
      __init__.py
      arb_scanner.py             ← wraps detect_orderbook_spread
      cross_market.py            ← wraps detect_cross_market
      correlated.py              ← wraps detect_correlated_markets
  signals/
    __init__.py
    btc_signals.py               ← re-exports from src.polymarket.alpaca_signals
    tuner.py                     ← re-exports from src.polymarket.tuner
  backtester/
    __init__.py
    engine.py                    ← BacktestRunner (delegates to src.backtest)
    data_loader.py               ← historical bar fetcher
    report.py                    ← results formatter + JSON writer
  dashboard/
    __init__.py
    api.py                       ← new endpoints: /api/engine/*, /api/strategies/*
    aggregator.py                ← re-exports src.dashboard.aggregator

data/
  engine_state.json              ← emergency stop persistence
  strategy_config.json           ← per-strategy enabled/allocation/schedule
  backtest_results/              ← backtest output JSON files

tests/trauto/                    ← new tests, mirrors trauto/ structure

=============================================================================
DESIGN DECISIONS
=============================================================================

ASYNC STRATEGY
  The engine uses asyncio throughout. All broker calls are wrapped in
  asyncio.to_thread() where the underlying library is sync (httpx, SQLAlchemy).
  No blocking I/O in the hot path. The tick loop targets ENGINE_TICK_MS (default
  100ms = 10 ticks/sec). This is NOT HFT — the goal is to never add latency
  beyond what the broker APIs themselves impose.

MIGRATION STRATEGY
  1. Create trauto/ package alongside src/ (no deletions yet)
  2. New code WRAPS existing src.* code via delegation
  3. Old tests still run and still pass (src/ unchanged)
  4. New tests validate trauto/ wrappers and new orchestration layer
  5. After all tests green: add _legacy suffix to src/ files being replaced
  6. After _legacy phase validates: remove _legacy files

DRY RUN DEFAULT
  engine.dry_run defaults to true in default.json. A running engine with
  dry_run=true will collect signals, pass them through risk, log intended
  orders, but never call broker.place_order(). Must be explicitly set false.

EMERGENCY STOP
  Persisted to data/engine_state.json. Written synchronously before any stop
  completes. Read at engine startup before accepting any strategy signals.
  Cannot be cleared programmatically — only via POST /api/engine/start.

SIGNAL PARAMS HOT-RELOAD
  trauto/signals/btc_signals.py re-exports get_cached_signals() from src.polymarket.
  trauto/signals/tuner.py apply_proposal() calls reload_signal_params() in src.polymarket.signals.
  CPython dict assignment under GIL is atomic — no locking needed.

CIRCUIT BREAKER
  Tracked in GlobalRiskManager._circuit_breaker per broker name.
  Trips after 3 consecutive errors. Auto-resumes after cooldown.
  3 trips in 1 hour → manual_resume_required flag.

STRATEGY STATE
  trauto/core/engine.py reads data/strategy_config.json at startup.
  In-process dict allows live updates without restart.
  Dashboard API writes strategy_config.json and notifies engine via event bus.

BACKTESTER ISOLATION
  BacktestRunner in trauto/backtester/engine.py never imports live broker clients.
  It uses data_loader.py (Alpaca bars only) or user-provided JSON for Polymarket.
  Writes results to data/backtest_results/<run_id>.json.

CONFIG LAYERING
  defaults → config/local.json → env vars (env wins).
  Secrets (.env only): API keys, private keys, tokens.
  Dot-notation access: config.get("engine.tick_ms").
  Type coercion: bool, int, float, str from env vars.

=============================================================================
GO-LIVE CHECKLIST (from dry_run=true to live)
=============================================================================

1. Set engine.dry_run = false in config/local.json or ENGINE_DRY_RUN=false
2. Set POLY_DRY_RUN=false (Polymarket execution)
3. Set PAPER_TRADING=true (Alpaca paper trading — never set false without Alpaca live creds)
4. Set DASHBOARD_API_TOKEN to a long random string
5. Set AUTH_SESSION_SECRET and AUTH_PASSWORD_PEPPER to long random strings
6. Set POLY_API_KEY, POLY_API_SECRET, POLY_PASSPHRASE, POLY_PRIVATE_KEY
7. Set ALPACA_API_KEY, ALPACA_API_SECRET
8. Confirm data/engine_state.json does NOT have emergency_stop: true
9. Confirm data/strategy_config.json has all intended strategies enabled
10. Confirm risk.global_daily_loss_limit is set to acceptable value
11. Confirm risk.circuit_breaker_cooldown_sec is set
12. Run POST /api/engine/start to clear any startup-applied emergency stop
13. Monitor /api/engine/status for tick_rate > 0 and strategies_loaded > 0
-->

# Trauto Architecture

Unified algorithmic trading platform covering equities (Alpaca) and prediction
markets (Polymarket). See the comment block above for the full technical spec.

## Quick Reference

| Layer | Package | Entry Point |
|-------|---------|-------------|
| Engine | `trauto.core.engine` | `TradingEngine.start()` |
| Config | `trauto.config` | `config.get("key")` |
| Brokers | `trauto.brokers` | `BrokerInterface` |
| Strategies | `trauto.strategies` | `BaseStrategy` |
| Risk | `trauto.core.risk` | `GlobalRiskManager` |
| Signals | `trauto.signals` | `BtcSignals` |
| Backtester | `trauto.backtester` | `BacktestRunner` |
| Dashboard API | `trauto.dashboard.api` | FastAPI router |
