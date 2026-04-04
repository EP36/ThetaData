"use client";

import { useEffect, useState } from "react";

import { EquityDrawdownCharts } from "@/components/dashboard/equity-drawdown-charts";
import { RecentTradesTable } from "@/components/dashboard/recent-trades-table";
import { RiskAlertsPanel } from "@/components/dashboard/risk-alerts-panel";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { SummaryCard } from "@/components/dashboard/summary-card";
import { CollapsibleSection } from "@/components/ui/collapsible-section";
import { PageHeader } from "@/components/ui/page-header";
import { StatePanel } from "@/components/ui/state-panel";
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
      <StatePanel
        title="Loading dashboard"
        description="Fetching portfolio health, recent trades, and risk posture."
      />
    );
  }

  const dailyTone = summary.dailyPnl >= 0 ? "positive" : "negative";
  const totalTone = summary.totalPnl >= 0 ? "positive" : "negative";

  return (
    <section className="space-y-4">
      <PageHeader
        eyebrow="Dashboard"
        title="Operational Overview"
        description="Key PnL, position exposure, and system readiness are prioritized for quick review."
        meta={<StatusBadge status={summary.systemStatus} />}
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard
          label="Total PnL"
          value={formatUsd(summary.totalPnl)}
          tone={totalTone}
          meta="Portfolio"
        />
        <SummaryCard
          label="Daily PnL"
          value={formatUsd(summary.dailyPnl)}
          tone={dailyTone}
          meta="Today"
        />
        <SummaryCard
          label="Active Positions"
          value={String(summary.openPositions)}
          meta="Open now"
        />
        <SummaryCard label="Equity" value={formatUsd(summary.equity)} meta="Net value" />
      </div>

      <CollapsibleSection
        title="Performance Trend"
        description="Review equity growth and drawdown progression without leaving the dashboard."
      >
        <EquityDrawdownCharts equityCurve={equity} drawdownCurve={drawdown} />
      </CollapsibleSection>

      <CollapsibleSection
        title="Recent Trades"
        description="Latest persisted fills and realized PnL outcomes."
        meta={
          <span className="rounded-full border border-[var(--line-soft)] px-3 py-1 text-xs font-medium text-[var(--muted)]">
            {trades.length}
          </span>
        }
      >
        <RecentTradesTable trades={trades} showHeader={false} />
      </CollapsibleSection>

      <CollapsibleSection
        title="Risk Alerts"
        description="Warnings that may require attention before paper trading resumes."
        meta={
          <span className="rounded-full border border-[var(--line-soft)] px-3 py-1 text-xs font-medium text-[var(--muted)]">
            {summary.riskAlerts.length}
          </span>
        }
      >
        <RiskAlertsPanel alerts={summary.riskAlerts} showHeader={false} />
      </CollapsibleSection>
    </section>
  );
}
