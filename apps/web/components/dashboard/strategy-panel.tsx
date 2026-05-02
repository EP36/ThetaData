"use client";

import type {
  ThetaRunnerHeartbeat,
  ThetaRunnerStatus,
  ThetaStrategyRecord,
  ThetaTradeEntry,
} from "@/lib/types";

type Props = {
  status: ThetaRunnerStatus | null;
  error?: boolean;
};

// ─── helpers ────────────────────────────────────────────────────────────────

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  const diffMs = Date.now() - d.getTime();
  if (diffMs < 0) return "just now";
  const secs = Math.floor(diffMs / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function fmtUsd(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(n);
}

function humanLabel(s: string): string {
  return s.replaceAll("_", " ");
}

// ─── pill / badge primitives ─────────────────────────────────────────────────

type PillStyle = { bg: string; fg: string };

const PILL: Record<string, PillStyle> = {
  live:        { bg: "#d1fae5", fg: "#065f46" },
  stale:       { bg: "#fef3c7", fg: "#92400e" },
  unavailable: { bg: "var(--surface-soft)", fg: "var(--muted)" },
  dry_run:     { bg: "var(--accent-soft)",  fg: "var(--accent-strong)" },
  live_mode:   { bg: "#fee2e2",             fg: "#991b1b" },
  submitted:   { bg: "#d1fae5",             fg: "#065f46" },
  rejected:    { bg: "#fee2e2",             fg: "#991b1b" },
  failed:      { bg: "#fef3c7",             fg: "#92400e" },
  idle:        { bg: "var(--surface-soft)", fg: "var(--muted)" },
};

function Pill({ styleKey, children }: { styleKey: string; children: React.ReactNode }) {
  const { bg, fg } = PILL[styleKey] ?? PILL.idle;
  return (
    <span className="ui-pill" style={{ background: bg, color: fg }}>
      {children}
    </span>
  );
}

// ─── skeleton / error states ─────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div className="space-y-3">
      <div className="glass-panel animate-pulse rounded-[1.5rem] p-4" style={{ minHeight: 72 }} />
      <div className="grid gap-3 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="glass-panel animate-pulse rounded-[1.5rem] p-4 sm:p-5" style={{ minHeight: 128 }} />
        ))}
      </div>
    </div>
  );
}

function ErrorState() {
  return (
    <div className="glass-panel rounded-[1.5rem] px-5 py-4 text-sm text-[var(--muted)]"
         style={{ borderTop: "3px solid var(--line-soft)" }}>
      Strategy status endpoint did not respond. Check that the API server is running.
    </div>
  );
}

// ─── Section A: Runner Status (live heartbeat) ───────────────────────────────

function runnerBadgeKey(hb: ThetaRunnerHeartbeat): string {
  if (!hb.available) return "unavailable";
  if (hb.stale) return "stale";
  return "live";
}

function runnerBadgeLabel(hb: ThetaRunnerHeartbeat): string {
  if (!hb.available) return "No heartbeat";
  if (hb.stale) return "Runner stale";
  return "Runner live";
}

function modeBadgeKey(mode: string | null): string {
  if (!mode) return "idle";
  return mode === "dry_run" ? "dry_run" : "live_mode";
}

function RunnerStatusSection({ hb }: { hb: ThetaRunnerHeartbeat }) {
  const statusKey = runnerBadgeKey(hb);
  const statusLabel = runnerBadgeLabel(hb);

  if (!hb.available) {
    return (
      <div className="glass-panel rounded-[1.5rem] p-4 sm:p-5"
           style={{ borderTop: "3px solid var(--line-soft)" }}>
        <div className="mb-1 flex items-center gap-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">Runner Status</p>
          <Pill styleKey="unavailable">{statusLabel}</Pill>
        </div>
        <p className="mt-1 text-xs text-[var(--muted)]">
          No heartbeat file found. Start the runner with{" "}
          <code className="rounded bg-[var(--surface-soft)] px-1 py-0.5 font-mono text-[0.7rem]">
            python -m scripts.run_strategies --dry-run
          </code>{" "}
          to begin emitting live status.
        </p>
      </div>
    );
  }

  return (
    <div
      className="glass-panel rounded-[1.5rem] p-4 sm:p-5"
      style={{ borderTop: `3px solid ${hb.stale ? "#f59e0b" : "#10b981"}` }}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">Runner Status</p>
        <Pill styleKey={statusKey}>{statusLabel}</Pill>
        {hb.mode && (
          <Pill styleKey={modeBadgeKey(hb.mode)}>
            {hb.mode === "dry_run" ? "Dry Run" : "Live"}
          </Pill>
        )}
      </div>

      <div className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
        <Row label="Last tick"   value={relativeTime(hb.lastTickAt)} />
        <Row label="Iterations"  value={hb.iterationsCompleted > 0 ? String(hb.iterationsCompleted) : "—"} />
        <Row label="Strategies"  value={hb.strategiesEvaluated.length > 0 ? hb.strategiesEvaluated.join(", ") : "—"} />
        <Row label="Last result" value={hb.lastResult ? humanLabel(hb.lastResult) : "—"} />
        {hb.selectedStrategy && (
          <Row label="Selected" value={hb.selectedStrategy} />
        )}
      </div>

      {hb.lastError && (
        <div className="mt-2 rounded-md bg-[#fee2e2] px-2.5 py-1.5">
          <p className="break-all text-xs leading-relaxed text-[#991b1b]">
            <span className="font-semibold">Last error: </span>{hb.lastError}
          </p>
        </div>
      )}

      {hb.stale && (
        <p className="mt-2 text-xs text-amber-700">
          Heartbeat is older than 5 minutes. The runner may have exited or stalled.
        </p>
      )}
    </div>
  );
}

// ─── Section B: Per-strategy cards ──────────────────────────────────────────

function tradeStatusBadgeKey(status: string | null): string {
  if (!status) return "idle";
  if (status in PILL) return status;
  return "idle";
}

function StrategyCard({ s }: { s: ThetaStrategyRecord }) {
  const hasActivity = s.tradeCount > 0;

  return (
    <div
      className="glass-panel rounded-[1.5rem] p-4 sm:p-5"
      style={{ borderTop: `3px solid ${hasActivity ? "var(--accent-strong)" : "var(--line-soft)"}` }}
    >
      <div className="mb-3 flex items-start justify-between gap-2">
        <p className="text-sm font-semibold tracking-[-0.01em] text-[var(--text)]">
          {s.displayName}
        </p>
        {s.lastStatus ? (
          <Pill styleKey={tradeStatusBadgeKey(s.lastStatus)}>
            {humanLabel(s.lastStatus)}
          </Pill>
        ) : (
          <Pill styleKey="idle">Idle</Pill>
        )}
      </div>

      {!hasActivity ? (
        <p className="text-xs text-[var(--muted)]">No trades logged yet</p>
      ) : (
        <dl className="space-y-1.5">
          <Row label="Last edge"     value={s.lastEdgeBps     !== null ? `${s.lastEdgeBps.toFixed(1)} bps`    : "—"} />
          <Row label="Last notional" value={s.lastNotionalUsd !== null ? fmtUsd(s.lastNotionalUsd)             : "—"} />
          <Row label="Total trades"  value={String(s.tradeCount)} />
          <Row label="Last trade"    value={relativeTime(s.lastTradeAt)} />
          {s.lastError && (
            <div className="mt-2 rounded-md bg-[#fee2e2] px-2.5 py-1.5">
              <p className="break-all text-xs leading-relaxed text-[#991b1b]">{s.lastError}</p>
            </div>
          )}
        </dl>
      )}
    </div>
  );
}

// ─── Section C: Trade log summary ────────────────────────────────────────────

function TradeLogSummary({ status }: { status: ThetaRunnerStatus }) {
  const { tradeStats: st } = status;
  if (st.total === 0) return null;

  const items: { label: string; value: string; styleKey?: string }[] = [
    { label: "Total",     value: String(st.total) },
    { label: "Submitted", value: String(st.submitted), styleKey: "submitted" },
    { label: "Dry run",   value: String(st.dryRun),    styleKey: "dry_run" },
    { label: "Rejected",  value: String(st.rejected),  styleKey: "rejected" },
    { label: "Failed",    value: String(st.failed),    styleKey: "failed" },
    { label: "Notional",  value: fmtUsd(st.totalNotionalUsd) },
  ];

  return (
    <div className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">
        Trade Log Summary · all-time
      </p>
      <div className="grid grid-cols-3 gap-x-4 gap-y-2 sm:grid-cols-6">
        {items.map(({ label, value, styleKey }) => {
          const color = styleKey ? (PILL[styleKey]?.fg ?? "var(--ink)") : "var(--ink)";
          return (
            <div key={label} className="flex flex-col gap-0.5">
              <span className="text-[0.65rem] font-semibold uppercase tracking-wider text-[var(--muted)]">
                {label}
              </span>
              <span className="text-base font-semibold tabular-nums" style={{ color }}>
                {value}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Section D: Recent trades (historical) ───────────────────────────────────

function ThetaTradeRow({ t }: { t: ThetaTradeEntry }) {
  const statusColor = PILL[t.status]?.fg ?? "var(--muted)";
  return (
    <tr className="border-t border-[var(--line-soft)]">
      <td className="py-2 pr-3 text-xs text-[var(--muted)]">{relativeTime(t.timestamp)}</td>
      <td className="py-2 pr-3 text-xs font-medium text-[var(--ink)]">{t.asset}/{t.quote}</td>
      <td className="py-2 pr-3 text-xs text-[var(--ink)]">{t.side.toUpperCase()}</td>
      <td className="py-2 pr-3 text-xs tabular-nums text-[var(--ink)]">{fmtUsd(t.notionalUsd)}</td>
      <td className="py-2 pr-3 text-xs tabular-nums text-[var(--ink)]">{t.expectedEdgeBps.toFixed(1)} bps</td>
      <td className="py-2 text-xs font-medium" style={{ color: statusColor }}>
        {humanLabel(t.status)}
      </td>
    </tr>
  );
}

function RecentTradesSection({ trades }: { trades: ThetaTradeEntry[] }) {
  if (trades.length === 0) return null;
  return (
    <div className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">
        Historical Telemetry · last {trades.length} trades
      </p>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              {["When", "Pair", "Side", "Notional", "Edge", "Status"].map((h) => (
                <th key={h} className="pb-2 pr-3 text-left text-[0.65rem] font-semibold uppercase tracking-wider text-[var(--muted)]">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => <ThetaTradeRow key={i} t={t} />)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── shared row helper ────────────────────────────────────────────────────────

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="ui-label shrink-0 text-[var(--muted)]">{label}</dt>
      <dd className="min-w-0 truncate text-right text-sm font-medium text-[var(--ink)]">{value}</dd>
    </div>
  );
}

// ─── root ─────────────────────────────────────────────────────────────────────

export function StrategyPanel({ status, error = false }: Props) {
  if (error)        return <ErrorState />;
  if (status === null) return <LoadingSkeleton />;

  return (
    <div className="space-y-3">
      {/* A — Live runner heartbeat */}
      <RunnerStatusSection hb={status.runnerStatus} />

      {/* B — Per-strategy cards (last known evaluation / trade) */}
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">
          Last Known Evaluation
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          {status.strategies.map((s) => (
            <StrategyCard key={s.name} s={s} />
          ))}
        </div>
      </div>

      {/* C — All-time trade log summary */}
      <TradeLogSummary status={status} />

      {/* D — Recent trades (historical telemetry) */}
      <RecentTradesSection trades={status.recentTrades} />
    </div>
  );
}
