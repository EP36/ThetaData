"use client";

import { useEffect, useState } from "react";

import { EquityDrawdownCharts } from "@/components/dashboard/equity-drawdown-charts";
import { RecentTradesTable } from "@/components/dashboard/recent-trades-table";
import { RiskAlertsPanel } from "@/components/dashboard/risk-alerts-panel";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { SummaryCard } from "@/components/dashboard/summary-card";
import { getDashboardData } from "@/lib/dashboard/service";
import type { DashboardSummary, TimeSeriesPoint, TradeRow } from "@/lib/types";

function formatUsd(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  }).format(value);
}

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [equity, setEquity] = useState<TimeSeriesPoint[]>([]);
  const [drawdown, setDrawdown] = useState<TimeSeriesPoint[]>([]);
  const [trades, setTrades] = useState<TradeRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function loadDashboard() {
      setLoading(true);
      const data = await getDashboardData();
      if (!cancelled) {
        setSummary(data.summary);
        setEquity(data.equityCurve);
        setDrawdown(data.drawdownCurve);
        setTrades(data.recentTrades);
        setLoading(false);
      }
    }

    void loadDashboard();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading || summary === null) {
    return (
      <section className="glass-panel panel-animate rounded-2xl p-4 text-sm text-[var(--muted)]">
        Loading dashboard...
      </section>
    );
  }

  const dailyTone = summary.dailyPnl >= 0 ? "positive" : "negative";
  const totalTone = summary.totalPnl >= 0 ? "positive" : "negative";

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <div>
          <h2 className="page-title font-semibold">Operational Dashboard</h2>
          <p className="text-sm text-[var(--muted)]">
            Portfolio health, system status, and execution telemetry in one view.
          </p>
        </div>
        <StatusBadge status={summary.systemStatus} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard label="Equity" value={formatUsd(summary.equity)} />
        <SummaryCard
          label="Daily PnL"
          value={formatUsd(summary.dailyPnl)}
          tone={dailyTone}
        />
        <SummaryCard
          label="Total PnL"
          value={formatUsd(summary.totalPnl)}
          tone={totalTone}
        />
        <SummaryCard label="Open Positions" value={String(summary.openPositions)} />
      </div>

      <EquityDrawdownCharts equityCurve={equity} drawdownCurve={drawdown} />

      <div className="grid gap-3 lg:grid-cols-[0.9fr_1.1fr]">
        <RiskAlertsPanel alerts={summary.riskAlerts} />
        <RecentTradesTable trades={trades} />
      </div>
    </section>
  );
}
