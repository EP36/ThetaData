"use client";

import type { TradesFilter } from "@/lib/types";

type TradesFiltersProps = {
  value: TradesFilter;
  onChange: (next: TradesFilter) => void;
  onApply: () => void;
  isLoading: boolean;
  showHeader?: boolean;
  embedded?: boolean;
};

export function TradesFilters({
  value,
  onChange,
  onApply,
  isLoading,
  showHeader = true,
  embedded = false
}: TradesFiltersProps) {
  return (
    <section className={embedded ? "" : "glass-panel rounded-[1.5rem] p-4 sm:p-5"}>
      {showHeader ? (
        <>
          <h3 className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">
            Trade Filters
          </h3>
          <p className="mt-1 text-sm leading-6 text-[var(--muted)]">
            Narrow the trade list by symbol, strategy, or time window.
          </p>
        </>
      ) : null}
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
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
          className="ui-button ui-button-primary w-full sm:w-auto"
        >
          {isLoading ? "Applying..." : "Apply Filters"}
        </button>
      </div>
    </section>
  );
}
