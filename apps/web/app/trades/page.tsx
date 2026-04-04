"use client";

import { useEffect, useState } from "react";

import { TradesFilters } from "@/components/trades/trades-filters";
import { TradesTable } from "@/components/trades/trades-table";
import { CollapsibleSection } from "@/components/ui/collapsible-section";
import { PageHeader } from "@/components/ui/page-header";
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

  const activeFilterCount = Object.values(filters).filter(Boolean).length;

  useEffect(() => {
    void loadTrades(DEFAULT_FILTERS);
  }, []);

  return (
    <section className="space-y-4">
      <PageHeader
        eyebrow="Trades"
        title="Trade Activity"
        description="Review recent trade history with symbol, strategy, and date filters."
        meta={
          <span className="rounded-full border border-[var(--line-soft)] bg-[var(--surface-soft)] px-3 py-2 text-sm font-medium text-[var(--muted)]">
            {isLoading ? "Refreshing" : `${rows.length} results`}
          </span>
        }
      />

      <div className="md:hidden">
        <CollapsibleSection
          title="Filters"
          description="Refine the trade list only when you need to."
          meta={
            <span className="rounded-full border border-[var(--line-soft)] px-3 py-1 text-xs font-medium text-[var(--muted)]">
              {activeFilterCount}
            </span>
          }
        >
          <TradesFilters
            value={filters}
            onChange={setFilters}
            onApply={() => void loadTrades(filters)}
            isLoading={isLoading}
            showHeader={false}
            embedded
          />
        </CollapsibleSection>
      </div>

      <div className="hidden md:block">
        <TradesFilters
          value={filters}
          onChange={setFilters}
          onApply={() => void loadTrades(filters)}
          isLoading={isLoading}
        />
      </div>

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
