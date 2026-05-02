"use client";

import type { ThetaRunnerStatus, ThetaStrategyRecord, ThetaTradeEntry } from "@/lib/types";

type Props = {
  status: ThetaRunnerStatus | null;
  error?: boolean;
};

// ─── helpers ────────────────────────────────────────────────────────────────

function relativeTime(iso: string | null): string {
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

function humanStatus(s: string): string {
  return s.replaceAll("_", " ");
}

// ─── badge variants ─────────────────────────────────────────────────────────

type BadgeVariant = "idle" | "dry_run" | "submitted" | "rejected" | "failed" | "default";

const BADGE: Record<BadgeVariant, { bg: string; fg: string; label: string }> = {
  idle:      { bg: "var(--surface-soft)",  fg: "var(--muted)",          label: "Idle"      },
  dry_run:   { bg: "var(--accent-soft)",   fg: "var(--accent-strong)",  label: "Dry run"   },
  submitted: { bg: "#d1fae5",              fg: "#065f46",               label: "Submitted" },
  rejected:  { bg: "#fee2e2",              fg: "#991b1b",               label: "Rejected"  },
  failed:    { bg: "#fef3c7",              fg: "#92400e",               label: "Failed"    },
  default:   { bg: "var(--surface-soft)",  fg: "var(--muted)",          label: ""          },
};

function resolveBadgeVariant(status: string | null): BadgeVariant {
  if (!status) return "idle";
  if (status in BADGE) return status as BadgeVariant;
  return "default";
}

function StatusBadge({ status }: { status: string | null }) {
  const v = resolveBadgeVariant(status);
  const { bg, fg, label } = BADGE[v];
  const text = v === "default" && status ? humanStatus(status) : label;
  return (
    <span className="ui-pill" style={{ background: bg, color: fg }}>
      {text}
    </span>
  );
}

// ─── skeleton / error / empty ────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="glass-panel animate-pulse rounded-[1.5rem] p-4 sm:p-5"
          style={{ minHeight: 128 }}
        />
      ))}
    </div>
  );
}

function ErrorState() {
  return (
    <div
      className="glass-panel rounded-[1.5rem] px-5 py-4 text-sm text-[var(--muted)]"
      style={{ borderTop: "3px solid var(--line-soft)" }}
    >
      Strategy status unavailable — the theta runner endpoint did not respond.
    </div>
  );
}

// ─── strategy card ───────────────────────────────────────────────────────────

function StrategyCard({ s }: { s: ThetaStrategyRecord }) {
  const hasActivity = s.tradeCount > 0;
  const borderColor = hasActivity ? "var(--accent-strong)" : "var(--line-soft)";

  return (
    <div
      className="glass-panel rounded-[1.5rem] p-4 sm:p-5"
      style={{ borderTop: `3px solid ${borderColor}` }}
    >
      <div className="mb-3 flex items-start justify-between gap-2">
        <p className="text-sm font-semibold tracking-[-0.01em] text-[var(--text)]">
          {s.displayName}
        </p>
        <StatusBadge status={s.lastStatus} />
      </div>

      {!hasActivity ? (
        <p className="text-xs text-[var(--muted)]">No trades logged yet</p>
      ) : (
        <dl className="space-y-1.5">
          <Row label="Edge"     value={s.lastEdgeBps     !== null ? `${s.lastEdgeBps.toFixed(1)} bps` : "—"} />
          <Row label="Notional" value={s.lastNotionalUsd !== null ? fmtUsd(s.lastNotionalUsd)          : "—"} />
          <Row label="Trades"   value={String(s.tradeCount)} />
          <Row label="Last"     value={relativeTime(s.lastTradeAt)} />
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

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="ui-label text-[var(--muted)]">{label}</dt>
      <dd className="text-sm font-medium text-[var(--ink)]">{value}</dd>
    </div>
  );
}

// ─── operator stats card ─────────────────────────────────────────────────────

function StatsCard({ status }: { status: ThetaRunnerStatus }) {
  const { tradeStats: st } = status;
  if (st.total === 0) return null;

  const items: { label: string; value: string; color?: string }[] = [
    { label: "Total",     value: String(st.total) },
    { label: "Submitted", value: String(st.submitted), color: "#065f46" },
    { label: "Dry run",   value: String(st.dryRun),    color: "var(--accent-strong)" },
    { label: "Rejected",  value: String(st.rejected),  color: "#991b1b" },
    { label: "Failed",    value: String(st.failed),    color: "#92400e" },
    { label: "Notional",  value: fmtUsd(st.totalNotionalUsd) },
  ];

  return (
    <div className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
      <p className="mb-3 text-sm font-semibold text-[var(--text)]">Trade Log Summary</p>
      <div className="grid grid-cols-3 gap-x-4 gap-y-2 sm:grid-cols-6">
        {items.map(({ label, value, color }) => (
          <div key={label} className="flex flex-col gap-0.5">
            <span className="text-[0.65rem] font-semibold uppercase tracking-wider text-[var(--muted)]">
              {label}
            </span>
            <span
              className="text-base font-semibold tabular-nums"
              style={{ color: color ?? "var(--ink)" }}
            >
              {value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── recent trades table ─────────────────────────────────────────────────────

const TRADE_STATUS_COLOR: Record<string, string> = {
  dry_run:   "text-[var(--accent-strong)]",
  submitted: "text-emerald-700",
  rejected:  "text-red-700",
  failed:    "text-amber-700",
};

function ThetaTradeRow({ t }: { t: ThetaTradeEntry }) {
  const statusClass = TRADE_STATUS_COLOR[t.status] ?? "text-[var(--muted)]";
  const side = t.side.toUpperCase();

  return (
    <tr className="border-t border-[var(--line-soft)]">
      <td className="py-2 pr-3 text-xs text-[var(--muted)]">{relativeTime(t.timestamp)}</td>
      <td className="py-2 pr-3 text-xs font-medium text-[var(--ink)]">{t.asset}/{t.quote}</td>
      <td className="py-2 pr-3 text-xs text-[var(--ink)]">{side}</td>
      <td className="py-2 pr-3 text-xs tabular-nums text-[var(--ink)]">{fmtUsd(t.notionalUsd)}</td>
      <td className="py-2 pr-3 text-xs tabular-nums text-[var(--ink)]">{t.expectedEdgeBps.toFixed(1)} bps</td>
      <td className={`py-2 text-xs font-medium ${statusClass}`}>{humanStatus(t.status)}</td>
    </tr>
  );
}

// ─── root component ──────────────────────────────────────────────────────────

export function StrategyPanel({ status, error = false }: Props) {
  if (error) return <ErrorState />;
  if (status === null) return <LoadingSkeleton />;

  const modeBg    = status.dryRun ? "var(--accent-soft)"   : "var(--danger)";
  const modeFg    = status.dryRun ? "var(--accent-strong)" : "#fff";
  const modeLabel = status.dryRun ? "Dry Run"              : "Live";

  return (
    <div className="space-y-3">
      {/* Mode bar */}
      <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
        <span className="ui-pill" style={{ background: modeBg, color: modeFg }}>
          {modeLabel}
        </span>
        <span>{status.totalTradeCount} total trades</span>
        {status.lastTradeAt && (
          <span>· last {relativeTime(status.lastTradeAt)}</span>
        )}
      </div>

      {/* Per-strategy cards */}
      <div className="grid gap-3 sm:grid-cols-3">
        {status.strategies.map((s) => (
          <StrategyCard key={s.name} s={s} />
        ))}
      </div>

      {/* Operator stats */}
      <StatsCard status={status} />

      {/* Recent trades table */}
      {status.recentTrades.length > 0 && (
        <div className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
          <p className="mb-3 text-sm font-semibold text-[var(--text)]">Recent Trades</p>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  {["When", "Pair", "Side", "Notional", "Edge", "Status"].map((h) => (
                    <th
                      key={h}
                      className="pb-2 pr-3 text-left text-[0.65rem] font-semibold uppercase tracking-wider text-[var(--muted)]"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {status.recentTrades.map((t, i) => (
                  <ThetaTradeRow key={i} t={t} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
