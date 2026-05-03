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
import { getStrategyPanelStatus } from "@/lib/api/client";
import { getDashboardData } from "@/lib/dashboard/service";
import { useOperationalOverview } from "@/lib/dashboard/use-operational-overview";
import type { ThetaRunnerStatus, TimeSeriesPoint, TradeRow } from "@/lib/types";

function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

function formatStatusValue(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  const secs = Math.floor((Date.now() - d.getTime()) / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ago`;
}

// Derive a system status string for the StatusBadge from overview data.
function deriveSystemStatus(
  runnerLive: boolean,
  runnerStale: boolean,
  coinbaseMode: string,
): string {
  if (!runnerLive && !runnerStale) return "backend_unavailable";
  if (runnerStale) return "dry_run";
  if (coinbaseMode === "live") return "polymarket_live"; // reuse green badge
  if (coinbaseMode === "dry_run") return "dry_run";
  return "trading_disabled";
}

export default function DashboardPage() {
  const overview = useOperationalOverview();

  // Charts + recent trades still come from the legacy service (equity curves, fills)
  const [equity, setEquity] = useState<TimeSeriesPoint[]>([]);
  const [drawdown, setDrawdown] = useState<TimeSeriesPoint[]>([]);
  const [trades, setTrades] = useState<TradeRow[]>([]);
  const [strategyStatus, setStrategyStatus] = useState<ThetaRunnerStatus | null>(null);
  const [strategyError, setStrategyError] = useState(false);
  const [chartsLoading, setChartsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      let thetaError = false;
      const [data, strategies] = await Promise.all([
        getDashboardData(),
        getStrategyPanelStatus().catch(() => { thetaError = true; return null; }),
      ]);
      if (!cancelled) {
        setEquity(data.equityCurve);
        setDrawdown(data.drawdownCurve);
        setTrades(data.recentTrades);
        setStrategyStatus(strategies);
        setStrategyError(thetaError);
        setChartsLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, []);

  // Loading state: wait for overview only (charts load in background)
  if (overview.loading) {
    return (
      <StatePanel
        title="Loading dashboard"
        description="Fetching portfolio health, recent trades, and risk posture."
      />
    );
  }

  const ov = overview.data;

  // ── derive display values ────────────────────────────────────────────────
  const systemStatus = ov
    ? deriveSystemStatus(ov.system.runnerLive, ov.system.runnerStale, ov.venues.coinbaseMode)
    : "backend_unavailable";

  const totalPnl = ov?.pnl.totalUsd ?? null;
  const dailyPnl = ov?.pnl.dailyUsd ?? null;
  const totalPnlTone = totalPnl === null ? "default" : totalPnl >= 0 ? "positive" : "negative";
  const dailyPnlTone = dailyPnl === null ? "default" : dailyPnl >= 0 ? "positive" : "negative";

  const balanceNote = ov?.balances.note || "estimated from trades";
  const warnings = ov?.health.warnings ?? [];
  const hasWarnings = warnings.length > 0;

  const freshness = overview.lastFetchedAt
    ? `Updated ${relativeTime(overview.lastFetchedAt.toISOString())}`
    : "";

  const riskAlerts: string[] = [
    ...(hasWarnings ? warnings : []),
    ...(ov?.system.runnerStale ? ["runner_stale"] : []),
  ];

  return (
    <section className="space-y-4">
      <PageHeader
        eyebrow="Dashboard"
        title="Operational Overview"
        description={
          freshness
            ? `Key PnL, position exposure, and system readiness. ${freshness}.`
            : "Key PnL, position exposure, and system readiness."
        }
        meta={<StatusBadge status={systemStatus} />}
      />

      {/* Row 1 — mode cards */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard
          label="Signal Provider"
          value={formatStatusValue(ov?.system.signalProvider ?? "—")}
          meta="Signals"
        />
        <SummaryCard
          label="Execution Venue"
          value={formatStatusValue(ov?.venues.executionVenue ?? "—")}
          meta={formatStatusValue(ov?.venues.coinbaseMode ?? "off")}
        />
        <SummaryCard
          label="Polymarket Mode"
          value={formatStatusValue(ov?.venues.polymarketMode ?? "—")}
          meta="Poly"
        />
        <SummaryCard
          label="Alpaca Mode"
          value={formatStatusValue(ov?.venues.alpacaMode ?? "—")}
          meta="Alpaca"
        />
      </div>

      {/* Row 2 — metric cards */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard
          label="Total PnL"
          value={formatUsd(totalPnl)}
          tone={totalPnlTone}
          meta={ov?.pnl.note ?? ""}
        />
        <SummaryCard
          label="Daily PnL"
          value={formatUsd(dailyPnl)}
          tone={dailyPnlTone}
          meta="Today (UTC)"
        />
        <SummaryCard
          label="Active Positions"
          value={String(ov?.positions.activeCount ?? 0)}
          meta={
            ov?.positions.ethQty
              ? `~${ov.positions.ethQty.toFixed(4)} ETH`
              : "Open now"
          }
        />
        <SummaryCard
          label="Total Balance"
          value={formatUsd(ov?.balances.totalUsd)}
          meta={balanceNote}
        />
      </div>

      {/* Health warning banner (only when degraded) */}
      {hasWarnings && (
        <div
          className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          role="alert"
        >
          <span className="font-semibold">System warnings: </span>
          {warnings.join(" · ")}
        </div>
      )}

      <CollapsibleSection
        title="Theta Strategies"
        description="Live state of theta strategies: edge evaluation, last execution, and trade stats."
        defaultOpen
      >
        <StrategyPanel status={strategyStatus} error={strategyError} />
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
        description="Warnings that may require attention before trading resumes."
        meta={
          <span className="rounded-full border border-[var(--line-soft)] px-3 py-1 text-xs font-medium text-[var(--muted)]">
            {riskAlerts.length}
          </span>
        }
      >
        <RiskAlertsPanel alerts={riskAlerts} showHeader={false} />
      </CollapsibleSection>
    </section>
  );
}
