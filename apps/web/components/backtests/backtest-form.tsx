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
    <section className="glass-panel rounded-2xl p-4 md:px-5">
      <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
        Backtest Inputs
      </h3>
      <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
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

      <div className="mt-4 rounded-xl border border-[var(--line-soft)] bg-[var(--panel-soft)] px-3 py-3 text-sm">
        <p className="font-semibold">Position Sizing Preview</p>
        <p className="mt-1 text-[var(--muted)]">
          `riskPerTrade = 1%` of account, `positionSize = risk / stopLoss%`, capped at `25%`.
        </p>
        <div className="mt-2 grid gap-2 md:grid-cols-2 lg:grid-cols-4">
          <p>Account: {formatUsd(DEFAULT_ACCOUNT_SIZE)}</p>
          <p>Risk / Trade: {formatUsd(riskPerTrade)}</p>
          <p>Stop Loss: {formatPct(stopLossPct)}</p>
          <p>Position Size: {formatPct(cappedPositionSizePct)}</p>
        </div>
      </div>

      <div className="mt-4">
        <button
          type="button"
          onClick={onRun}
          disabled={isRunning}
          className="ui-button ui-button-primary"
        >
          {isRunning ? "Running..." : "Run Backtest"}
        </button>
      </div>
    </section>
  );
}
