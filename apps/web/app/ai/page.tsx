"use client";

import { useEffect, useState } from "react";

import { TableScrollArea } from "@/components/table/table-scroll-area";
import { CollapsibleSection } from "@/components/ui/collapsible-section";
import { PageHeader } from "@/components/ui/page-header";
import { StatePanel } from "@/components/ui/state-panel";
import { getAIInsightsData } from "@/lib/ai/service";
import type { AIAnalysisEntry, AIInsightsData, AIProposal } from "@/lib/types";

function formatPct(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function statusBadgeClass(status: string): string {
  switch (status) {
    case "applied":
      return "border-[var(--accent-ring)] bg-[var(--accent-soft)] text-[var(--accent-strong)]";
    case "pending":
      return "border-[var(--warning-ring)] bg-[var(--warning-soft)] text-[var(--warning-strong)]";
    case "rejected":
      return "border-[var(--danger-ring)] bg-[var(--danger-soft)] text-[var(--danger)]";
    default:
      return "border-[var(--line-soft)] bg-[var(--surface-soft)] text-[var(--muted)]";
  }
}

function outcomeTone(outcome: string | null): string {
  if (!outcome) return "text-[var(--muted)]";
  if (outcome === "auto_applied") return "text-[var(--accent-strong)]";
  if (outcome.includes("queued")) return "text-[var(--warning-strong)]";
  if (outcome === "safety_rejected") return "text-[var(--danger)]";
  return "text-[var(--text)]";
}

function DataRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-sm leading-6 text-[var(--muted)]">{label}</span>
      <span className="text-right text-sm font-medium text-[var(--text)]">{value}</span>
    </div>
  );
}

function ParamDiffRow({
  name,
  current,
  proposed,
}: {
  name: string;
  current: number | undefined;
  proposed: number;
}) {
  const changed = current !== undefined && current !== proposed;
  return (
    <tr className={changed ? "bg-[var(--warning-soft)]" : ""}>
      <td className="font-mono text-xs">{name}</td>
      <td className="numeric font-mono text-xs">{current !== undefined ? current.toFixed(4) : "—"}</td>
      <td className={`numeric font-mono text-xs ${changed ? "font-semibold text-[var(--warning-strong)]" : ""}`}>
        {proposed.toFixed(4)}
      </td>
    </tr>
  );
}

function ProposalCard({ proposal }: { proposal: AIProposal }) {
  return (
    <article className="rounded-[1.25rem] border border-[var(--line-soft)] bg-[var(--panel-soft)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">
              Proposal #{proposal.id}
            </p>
            <span
              className={`rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.12em] ${statusBadgeClass(proposal.status)}`}
            >
              {proposal.status}
            </span>
          </div>
          <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
            {formatDate(proposal.created_at)}
          </p>
        </div>
        <div className="text-right">
          <p className="ui-label">Confidence</p>
          <p className="mt-2 text-lg font-semibold tracking-[-0.03em] text-[var(--text)]">
            {(proposal.confidence * 100).toFixed(0)}%
          </p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
        <div className="rounded-2xl bg-[var(--panel)] px-3 py-3">
          <p className="ui-label">Trades</p>
          <p className="mt-2 font-semibold text-[var(--text)]">{proposal.trade_count}</p>
        </div>
        <div className="rounded-2xl bg-[var(--panel)] px-3 py-3">
          <p className="ui-label">Win Rate</p>
          <p className="mt-2 font-semibold text-[var(--text)]">{formatPct(proposal.win_rate)}</p>
        </div>
        <div className="rounded-2xl bg-[var(--panel)] px-3 py-3">
          <p className="ui-label">Avg P&amp;L</p>
          <p className="mt-2 font-semibold text-[var(--text)]">{formatPct(proposal.avg_pnl_pct)}</p>
        </div>
      </div>

      {proposal.key_findings.length > 0 ? (
        <div className="mt-4">
          <p className="ui-label">Key Findings</p>
          <ul className="mt-2 space-y-1">
            {proposal.key_findings.map((f, i) => (
              <li key={i} className="text-sm leading-6 text-[var(--text)]">
                • {f}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {proposal.warnings.length > 0 ? (
        <div className="mt-4">
          <p className="ui-label text-[var(--warning-strong)]">Warnings</p>
          <ul className="mt-2 space-y-1">
            {proposal.warnings.map((w, i) => (
              <li key={i} className="text-sm leading-6 text-[var(--warning-strong)]">
                • {w}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <details className="mt-4 rounded-2xl border border-[var(--line-soft)] bg-[var(--panel)]">
        <summary className="cursor-pointer list-none px-3 py-3 text-sm font-medium text-[var(--text)]">
          Parameter changes
        </summary>
        <div className="border-t border-[var(--line-soft)] px-3 py-3">
          <TableScrollArea minWidth={480}>
            <table className="data-table text-xs">
              <colgroup>
                <col className="w-[60%]" />
                <col className="w-[20%]" />
                <col className="w-[20%]" />
              </colgroup>
              <thead>
                <tr>
                  <th>Parameter</th>
                  <th className="numeric">Current</th>
                  <th className="numeric">Proposed</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(proposal.proposed_params).map(([name, val]) => (
                  <ParamDiffRow
                    key={name}
                    name={name}
                    current={proposal.current_params[name]}
                    proposed={val}
                  />
                ))}
              </tbody>
            </table>
          </TableScrollArea>
        </div>
      </details>

      <details className="mt-3 rounded-2xl border border-[var(--line-soft)] bg-[var(--panel)]">
        <summary className="cursor-pointer list-none px-3 py-3 text-sm font-medium text-[var(--text)]">
          Reasoning
        </summary>
        <div className="border-t border-[var(--line-soft)] px-3 py-3 text-sm leading-6 text-[var(--muted)] whitespace-pre-wrap">
          {proposal.reasoning || "No reasoning provided."}
        </div>
      </details>

      {(proposal.applied_at ?? proposal.rejected_at ?? proposal.auto_apply_after) ? (
        <div className="mt-4 grid gap-3">
          {proposal.applied_at ? (
            <DataRow label="Applied at" value={formatDate(proposal.applied_at)} />
          ) : null}
          {proposal.applied_by ? (
            <DataRow label="Applied by" value={proposal.applied_by} />
          ) : null}
          {proposal.rejected_at ? (
            <DataRow label="Rejected at" value={formatDate(proposal.rejected_at)} />
          ) : null}
          {proposal.auto_apply_after && proposal.status === "pending" ? (
            <DataRow label="Auto-apply after" value={formatDate(proposal.auto_apply_after)} />
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function AnalysisLogRow({ entry }: { entry: AIAnalysisEntry }) {
  return (
    <tr>
      <td>{formatDate(entry.created_at)}</td>
      <td className={outcomeTone(entry.outcome)}>{entry.outcome ?? "—"}</td>
      <td className="numeric">{entry.confidence != null ? `${(entry.confidence * 100).toFixed(0)}%` : "—"}</td>
      <td className="numeric">{entry.trade_count ?? "—"}</td>
      <td className="numeric">{entry.win_rate != null ? formatPct(entry.win_rate) : "—"}</td>
      <td className="numeric">{entry.avg_pnl_pct != null ? formatPct(entry.avg_pnl_pct) : "—"}</td>
      <td className="numeric">{entry.proposal_id ?? "—"}</td>
      <td className="numeric">{entry.tokens_used.toLocaleString()}</td>
    </tr>
  );
}

export default function AIInsightsPage() {
  const [data, setData] = useState<AIInsightsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const next = await getAIInsightsData();
        if (!cancelled) setData(next);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Unable to load AI insights.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <StatePanel
        title="Loading AI insights"
        description="Fetching signal parameters, proposals, and analysis history."
      />
    );
  }

  if (error || !data) {
    return (
      <StatePanel
        title="AI insights unavailable"
        description={error ?? "Unable to load AI insights from backend."}
        tone="danger"
      />
    );
  }

  const paramEntries = Object.entries(data.signalParams).sort(([a], [b]) => a.localeCompare(b));

  return (
    <section className="space-y-4">
      <PageHeader
        eyebrow="AI"
        title="Insights"
        description="Autonomous parameter tuning — current signal params, pending and applied proposals, and analysis run history."
      />

      <CollapsibleSection
        title="Signal Parameters"
        description={`Version ${data.signalParamsMeta.version} · updated ${formatDate(data.signalParamsMeta.updated_at)} by ${data.signalParamsMeta.updated_by}`}
        defaultOpen
      >
        {paramEntries.length === 0 ? (
          <p className="text-sm text-[var(--muted)]">No signal parameters found.</p>
        ) : (
          <TableScrollArea minWidth={480}>
            <table className="data-table text-sm">
              <colgroup>
                <col className="w-[70%]" />
                <col className="w-[30%]" />
              </colgroup>
              <thead>
                <tr>
                  <th>Parameter</th>
                  <th className="numeric">Value</th>
                </tr>
              </thead>
              <tbody>
                {paramEntries.map(([name, value]) => (
                  <tr key={name}>
                    <td className="font-mono text-xs">{name}</td>
                    <td className="numeric font-mono text-xs">{value.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScrollArea>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title="Proposals"
        description={`${data.proposals.length} most recent · pending proposals may auto-apply on timer`}
        defaultOpen
      >
        {data.proposals.length === 0 ? (
          <p className="text-sm text-[var(--muted)]">No proposals yet.</p>
        ) : (
          <div className="space-y-4">
            {data.proposals.map((proposal) => (
              <ProposalCard key={proposal.id} proposal={proposal} />
            ))}
          </div>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title="Analysis Log"
        description="Recent automated analysis runs and their outcomes."
      >
        {data.analysisLog.length === 0 ? (
          <p className="text-sm text-[var(--muted)]">No analysis runs yet.</p>
        ) : (
          <TableScrollArea minWidth={860}>
            <table className="data-table text-sm">
              <colgroup>
                <col className="w-[22%]" />
                <col className="w-[18%]" />
                <col className="w-[10%]" />
                <col className="w-[8%]" />
                <col className="w-[10%]" />
                <col className="w-[10%]" />
                <col className="w-[10%]" />
                <col className="w-[12%]" />
              </colgroup>
              <thead>
                <tr>
                  <th>Run At</th>
                  <th>Outcome</th>
                  <th className="numeric">Confidence</th>
                  <th className="numeric">Trades</th>
                  <th className="numeric">Win Rate</th>
                  <th className="numeric">Avg P&amp;L</th>
                  <th className="numeric">Proposal</th>
                  <th className="numeric">Tokens</th>
                </tr>
              </thead>
              <tbody>
                {data.analysisLog.map((entry) => (
                  <AnalysisLogRow key={entry.id} entry={entry} />
                ))}
              </tbody>
            </table>
          </TableScrollArea>
        )}
      </CollapsibleSection>
    </section>
  );
}
