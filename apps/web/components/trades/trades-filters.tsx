"use client";

import type { TradesFilter } from "@/lib/types";

type TradesFiltersProps = {
  value: TradesFilter;
  onChange: (next: TradesFilter) => void;
  onApply: () => void;
  isLoading: boolean;
};

export function TradesFilters({
  value,
  onChange,
  onApply,
  isLoading
}: TradesFiltersProps) {
  return (
    <section className="glass-panel rounded-3xl p-4 md:px-5">
      <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
        Trade Filters
      </h3>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="ui-label">Symbol</span>
          <input
            value={value.symbol}
            onChange={(event) =>
              onChange({ ...value, symbol: event.target.value.toUpperCase() })
            }
            className="ui-input"
            placeholder="SPY"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="ui-label">Strategy</span>
          <select
            value={value.strategy}
            onChange={(event) => onChange({ ...value, strategy: event.target.value })}
            className="ui-select"
          >
            <option value="">All</option>
            <option value="moving_average_crossover">Moving Average Crossover</option>
            <option value="rsi_mean_reversion">RSI Mean Reversion</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="ui-label">Start Date</span>
          <input
            type="date"
            value={value.startDate}
            onChange={(event) => onChange({ ...value, startDate: event.target.value })}
            className="ui-input"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="ui-label">End Date</span>
          <input
            type="date"
            value={value.endDate}
            onChange={(event) => onChange({ ...value, endDate: event.target.value })}
            className="ui-input"
          />
        </label>
      </div>
      <div className="mt-4">
        <button
          type="button"
          onClick={onApply}
          disabled={isLoading}
          className="ui-button ui-button-primary"
        >
          {isLoading ? "Applying..." : "Apply Filters"}
        </button>
      </div>
    </section>
  );
}
