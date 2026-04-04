"use client";

import { useEffect, useState } from "react";

import { TradesFilters } from "@/components/trades/trades-filters";
import { TradesTable } from "@/components/trades/trades-table";
import { StatePanel } from "@/components/ui/state-panel";
import { getTrades } from "@/lib/trades/service";
import type { TradeRow, TradesFilter } from "@/lib/types";

const DEFAULT_FILTERS: TradesFilter = {
  symbol: "",
  strategy: "",
  startDate: "",
  endDate: ""
};

export default function TradesPage() {
  const [filters, setFilters] = useState<TradesFilter>(DEFAULT_FILTERS);
  const [rows, setRows] = useState<TradeRow[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const loadTrades = async (nextFilters: TradesFilter) => {
    setIsLoading(true);
    const nextRows = await getTrades(nextFilters);
    setRows(nextRows);
    setIsLoading(false);
  };

  useEffect(() => {
    void loadTrades(DEFAULT_FILTERS);
  }, []);

  return (
    <section className="space-y-5">
      <article className="glass-panel rounded-[1.75rem] p-5 sm:p-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="ui-label">Trades</p>
            <h2 className="page-title mt-3 font-semibold">Trade Activity</h2>
            <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
              Review recent trade history with symbol, strategy, and date filters.
            </p>
          </div>
          <span className="rounded-full border border-[var(--line-soft)] bg-[var(--surface-soft)] px-3 py-2 text-sm font-medium text-[var(--muted)]">
            {isLoading ? "Refreshing" : `${rows.length} results`}
          </span>
        </div>
      </article>

      <TradesFilters
        value={filters}
        onChange={setFilters}
        onApply={() => void loadTrades(filters)}
        isLoading={isLoading}
      />

      {isLoading ? (
        <StatePanel
          title="Loading trades"
          description="Fetching persisted paper trades with the current filter set."
        />
      ) : rows.length === 0 ? (
        <StatePanel
          title="No trades match"
          description="No persisted paper trades were found for the current filters. Critical data is still available once trades are recorded."
        />
      ) : (
        <TradesTable rows={rows} />
      )}
    </section>
  );
}
