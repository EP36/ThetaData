"use client";

import type { BacktestFormInput } from "@/lib/types";

type BacktestFormProps = {
  value: BacktestFormInput;
  onChange: (next: BacktestFormInput) => void;
  onRun: () => void;
  isRunning: boolean;
};

export function BacktestForm({
  value,
  onChange,
  onRun,
  isRunning
}: BacktestFormProps) {
  const updateField = <K extends keyof BacktestFormInput>(
    field: K,
    nextValue: BacktestFormInput[K]
  ) => {
    onChange({ ...value, [field]: nextValue });
  };

  return (
    <section className="glass-panel rounded-3xl p-4 md:px-5">
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
          </select>
        </label>
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
