"use client";

import type { StrategyPanelStatus } from "@/lib/types";

type Props = {
  status: StrategyPanelStatus | null;
};

function formatRelativeTime(isoString: string): string {
  const target = new Date(isoString).getTime();
  const now = Date.now();
  const diffMs = target - now;
  if (diffMs <= 0) return "now";
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 60) return `${diffMin}m`;
  const diffHr = Math.floor(diffMin / 60);
  const remMin = diffMin % 60;
  return remMin > 0 ? `${diffHr}h ${remMin}m` : `${diffHr}h`;
}

function ModeBadge({ dryRun }: { dryRun: boolean }) {
  return dryRun ? (
    <span
      className="ui-pill"
      style={{ background: "var(--accent-soft)", color: "var(--accent-strong)" }}
    >
      Dry Run
    </span>
  ) : (
    <span
      className="ui-pill"
      style={{ background: "var(--danger)", color: "#fff" }}
    >
      Live
    </span>
  );
}

function StrategyCard({
  title,
  enabled,
  dryRun,
  rows,
}: {
  title: string;
  enabled: boolean;
  dryRun: boolean;
  rows: { label: string; value: string }[];
}) {
  return (
    <div
      className="glass-panel rounded-[1.5rem] p-4 sm:p-5"
      style={{
        borderTop: `3px solid ${enabled ? "var(--accent-strong)" : "var(--line-soft)"}`,
      }}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="text-sm font-semibold tracking-[-0.01em] text-[var(--text)]">{title}</p>
        <div className="flex items-center gap-2">
          <span
            className="ui-pill"
            style={{
              background: enabled ? "var(--accent-soft)" : "var(--surface-soft)",
              color: enabled ? "var(--accent-strong)" : "var(--muted)",
            }}
          >
            {enabled ? "Enabled" : "Disabled"}
          </span>
          <ModeBadge dryRun={dryRun} />
        </div>
      </div>
      <dl className="space-y-1.5">
        {rows.map(({ label, value }) => (
          <div key={label} className="flex items-center justify-between gap-2">
            <dt className="ui-label text-[var(--muted)]">{label}</dt>
            <dd className="text-sm font-medium text-[var(--ink)]">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="glass-panel animate-pulse rounded-[1.5rem] p-4 sm:p-5"
          style={{ minHeight: 120 }}
        />
      ))}
    </div>
  );
}

export function StrategyPanel({ status }: Props) {
  if (status === null) return <LoadingSkeleton />;

  const { polymarketArb, fundingRateArb, marketMaker } = status;

  const fundingRateRows: { label: string; value: string }[] = [
    {
      label: "Funding Rate",
      value:
        fundingRateArb.fundingRate !== null
          ? `${(fundingRateArb.fundingRate * 100).toFixed(4)}%`
          : "—",
    },
    {
      label: "Next Window",
      value:
        fundingRateArb.nextFundingAt !== null
          ? formatRelativeTime(fundingRateArb.nextFundingAt)
          : "—",
    },
    {
      label: "Positions",
      value: String(fundingRateArb.activePositions),
    },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <StrategyCard
        title="Polymarket Arb"
        enabled={polymarketArb.enabled}
        dryRun={polymarketArb.dryRun}
        rows={[{ label: "Positions", value: String(polymarketArb.activePositions) }]}
      />
      <StrategyCard
        title="Funding Rate Arb"
        enabled={fundingRateArb.enabled}
        dryRun={fundingRateArb.dryRun}
        rows={fundingRateRows}
      />
      <StrategyCard
        title="Market Maker"
        enabled={marketMaker.enabled}
        dryRun={marketMaker.dryRun}
        rows={[{ label: "Positions", value: String(marketMaker.activePositions) }]}
      />
    </div>
  );
}
