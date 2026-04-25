"use client";

import { useEffect, useState } from "react";

import { EquityDrawdownCharts } from "@/components/dashboard/equity-drawdown-charts";
import { RecentTradesTable } from "@/components/dashboard/recent-trades-table";
import { RiskAlertsPanel } from "@/components/dashboard/risk-alerts-panel";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { StrategyPanel } from "@/components/dashboard/strategy-panel";
import { SummaryCard } from "@/components/dashboard/summary-card";
import { CollapsibleSection } from "@/components/ui/collapsible-section";
import { PageHeader } from "@/components/ui/page-header";
import { StatePanel } from "@/components/ui/state-panel";
import { getDashboardSummary, getStrategyPanelStatus } from "@/lib/api/client";
import { getDashboardData } from "@/lib/dashboard/service";
import type { DashboardSummary, StrategyPanelStatus, TimeSeriesPoint, TradeRow } from "@/lib/types";

const BALANCE_POLL_MS = 60_000;

function formatUsd(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  }).format(value);
}

function formatStatusValue(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [equity, setEquity] = useState<TimeSeriesPoint[]>([]);
  const [drawdown, setDrawdown] = useState<TimeSeriesPoint[]>([]);
  const [trades, setTrades] = useState<TradeRow[]>([]);
  const [strategyStatus, setStrategyStatus] = useState<StrategyPanelStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function loadDashboard() {
      setLoading(true);
      const [data, strategies] = await Promise.all([
        getDashboardData(),
        getStrategyPanelStatus().catch(() => null),
      ]);
      if (!cancelled) {
        setSummary(data.summary);
        setEquity(data.equityCurve);
        setDrawdown(data.drawdownCurve);
        setTrades(data.recentTrades);
        setStrategyStatus(strategies);
        setLoading(false);
      }
    }

    void loadDashboard();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const updated = await getDashboardSummary();
        setSummary((prev) =>
          prev === null
            ? prev
            : {
                ...prev,
                equity: updated.equity,
                equityBreakdown: updated.equityBreakdown ?? prev.equityBreakdown,
                totalDeposited: updated.totalDeposited ?? prev.totalDeposited,
                totalPnl: updated.totalPnl,
              }
        );
      } catch {
        // leave stale value; next tick will retry
      }
    }, BALANCE_POLL_MS);
    return () => clearInterval(id);
  }, []);

  if (loading || summary === null) {
    return (
      <StatePanel
        title="Loading dashboard"
        description="Fetching portfolio health, recent trades, and risk posture."
      />
    );
  }

  const isPolymarket = summary.tradingStatus.tradingVenue === "polymarket";
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
          label="Signal Provider"
          value={formatStatusValue(summary.tradingStatus.signalProvider)}
          meta="Signals"
        />
        <SummaryCard
          label="Execution Venue"
          value={formatStatusValue(summary.tradingStatus.tradingVenue)}
          meta={formatStatusValue(summary.tradingStatus.executionAdapter)}
        />
        <SummaryCard
          label="Polymarket Mode"
          value={formatStatusValue(summary.tradingStatus.polyTradingMode)}
          meta={summary.tradingStatus.polyDryRun ? "Dry run on" : "Dry run off"}
        />
        <SummaryCard
          label="Alpaca Mode"
          value={formatStatusValue(summary.tradingStatus.alpacaTradingMode)}
          meta={
            summary.tradingStatus.paperTradingEnabled
              ? "Paper trading on"
              : "Paper trading off"
          }
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard
          label="Total PnL"
          value={formatUsd(summary.totalPnl)}
          tone={totalTone}
          meta={summary.totalDeposited ? `vs $${summary.totalDeposited.toFixed(0)} deposited` : "Portfolio"}
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
        <SummaryCard
          label="Total Balance"
          value={summary.equity !== null ? formatUsd(summary.equity) : "Unavailable"}
          meta={
            isPolymarket && summary.equityBreakdown
              ? `Poly: ${formatUsd(summary.equityBreakdown.polymarketUsdc)} | HL: ${formatUsd(summary.equityBreakdown.hyperliquidUsdc)}`
              : isPolymarket
              ? "Polygon wallet"
              : "Net value"
          }
        />
      </div>

      <CollapsibleSection
        title="Strategy Status"
        description="Live state of the three active trading strategies."
        defaultOpen={false}
      >
        <StrategyPanel status={strategyStatus} />
      </CollapsibleSection>

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
        description={`Warnings that may require attention before ${isPolymarket ? "live trading resumes" : "paper trading resumes"}.`}
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
