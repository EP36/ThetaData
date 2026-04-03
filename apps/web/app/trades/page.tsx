"use client";

import { useEffect, useState } from "react";

import { TradesFilters } from "@/components/trades/trades-filters";
import { TradesTable } from "@/components/trades/trades-table";
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
    <section className="space-y-4">
      <div className="px-1">
        <h2 className="page-title font-semibold">Trades</h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Review recent trade history with symbol, strategy, and date filters.
        </p>
      </div>

      <TradesFilters
        value={filters}
        onChange={setFilters}
        onApply={() => void loadTrades(filters)}
        isLoading={isLoading}
      />

      {isLoading ? (
        <div className="glass-panel rounded-2xl p-5 text-sm text-[var(--muted)]">
          Loading trades...
        </div>
      ) : rows.length === 0 ? (
        <div className="glass-panel rounded-2xl p-5 text-sm text-[var(--muted)]">
          No persisted paper trades yet. Keep paper trading disabled for safety, or enable it
          intentionally when you are ready to simulate execution.
        </div>
      ) : (
        <TradesTable rows={rows} />
      )}
    </section>
  );
}
