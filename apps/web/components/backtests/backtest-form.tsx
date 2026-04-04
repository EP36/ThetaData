"use client";

import type { BacktestFormInput } from "@/lib/types";

type BacktestFormProps = {
  value: BacktestFormInput;
  onChange: (next: BacktestFormInput) => void;
  onRun: () => void;
  isRunning: boolean;
};

const DEFAULT_ACCOUNT_SIZE = 100_000;
const RISK_PER_TRADE_PCT = 0.01;
const MAX_POSITION_SIZE_PCT = 0.25;
const STRATEGY_STOP_LOSS_PCT: Record<BacktestFormInput["strategy"], number> = {
  moving_average_crossover: 0.02,
  rsi_mean_reversion: 0.015,
  breakout_momentum: 0.02,
  vwap_mean_reversion: 0.015
};

function formatUsd(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  }).format(value);
}

function formatPct(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

export function BacktestForm({
  value,
  onChange,
  onRun,
  isRunning
}: BacktestFormProps) {
  const stopLossPct = STRATEGY_STOP_LOSS_PCT[value.strategy];
  const riskPerTrade = DEFAULT_ACCOUNT_SIZE * RISK_PER_TRADE_PCT;
  const rawPositionSizePct = RISK_PER_TRADE_PCT / stopLossPct;
  const cappedPositionSizePct = Math.min(rawPositionSizePct, MAX_POSITION_SIZE_PCT);

  const updateField = <K extends keyof BacktestFormInput>(
    field: K,
    nextValue: BacktestFormInput[K]
  ) => {
    onChange({ ...value, [field]: nextValue });
  };

  return (
    <section className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
      <h3 className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">
        Backtest Inputs
      </h3>
      <p className="mt-1 text-sm leading-6 text-[var(--muted)]">
        Configure the simulation window and strategy, then review position sizing before you run.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <label className="flex flex-col gap-1 text-sm">
          <span className="ui-label">Symbol</span>
          <input
            value={value.symbol}
            onChange={(event) => updateField("symbol", event.target.value.toUpperCase())}
            className="ui-input"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="ui-label">Timeframe</span>
          <select
            value={value.timeframe}
            onChange={(event) => updateField("timeframe", event.target.value)}
            className="ui-select"
          >
            <option value="1h">1h</option>
            <option value="4h">4h</option>
            <option value="1d">1d</option>
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="ui-label">Start Date</span>
          <input
            type="date"
            value={value.startDate}
            onChange={(event) => updateField("startDate", event.target.value)}
            className="ui-input"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="ui-label">End Date</span>
          <input
            type="date"
            value={value.endDate}
            onChange={(event) => updateField("endDate", event.target.value)}
            className="ui-input"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="ui-label">Strategy</span>
          <select
            value={value.strategy}
            onChange={(event) =>
              updateField(
                "strategy",
                event.target.value as BacktestFormInput["strategy"]
              )
            }
            className="ui-select"
          >
            <option value="moving_average_crossover">Moving Average Crossover</option>
            <option value="rsi_mean_reversion">RSI Mean Reversion</option>
            <option value="breakout_momentum">Breakout Momentum</option>
            <option value="vwap_mean_reversion">VWAP Mean Reversion</option>
          </select>
        </label>
      </div>

      <div className="mt-4 rounded-[1.1rem] border border-[var(--line-soft)] bg-[var(--panel-soft)] px-4 py-3.5 text-sm">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm font-semibold tracking-[-0.02em] text-[var(--text)]">
            Position Sizing Preview
          </p>
          <p className="text-xs font-medium uppercase tracking-[0.12em] text-[var(--muted)]">
            1% risk • 25% max
          </p>
        </div>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Risk divided by stop loss, then capped.
        </p>
        <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div className="rounded-[0.95rem] bg-[var(--panel)] px-3 py-2.5">
            <p className="ui-label">Account</p>
            <p className="mt-1.5 font-semibold">{formatUsd(DEFAULT_ACCOUNT_SIZE)}</p>
          </div>
          <div className="rounded-[0.95rem] bg-[var(--panel)] px-3 py-2.5">
            <p className="ui-label">Risk / Trade</p>
            <p className="mt-1.5 font-semibold">{formatUsd(riskPerTrade)}</p>
          </div>
          <div className="rounded-[0.95rem] bg-[var(--panel)] px-3 py-2.5">
            <p className="ui-label">Stop Loss</p>
            <p className="mt-1.5 font-semibold">{formatPct(stopLossPct)}</p>
          </div>
          <div className="rounded-[0.95rem] bg-[var(--panel)] px-3 py-2.5">
            <p className="ui-label">Position Size</p>
            <p className="mt-1.5 font-semibold">{formatPct(cappedPositionSizePct)}</p>
          </div>
        </div>
      </div>

      <div className="mt-4">
        <button
          type="button"
          onClick={onRun}
          disabled={isRunning}
          className="ui-button ui-button-primary w-full sm:w-auto"
        >
          {isRunning ? "Running..." : "Run Backtest"}
        </button>
      </div>
    </section>
  );
}
