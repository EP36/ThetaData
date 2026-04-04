"use client";

import { useEffect, useState } from "react";

import { TableScrollArea } from "@/components/table/table-scroll-area";
import { CollapsibleSection } from "@/components/ui/collapsible-section";
import { PageHeader } from "@/components/ui/page-header";
import { StatePanel } from "@/components/ui/state-panel";
import { getAnalyticsData } from "@/lib/analytics/service";
import type { AnalyticsData } from "@/lib/analytics/service";
import type {
  RollingMetricPoint,
  StrategyAnalyticsRecord,
  StrategyScore,
  WorkerSymbolDecision
} from "@/lib/types";

function formatPct(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

function formatUsd(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  }).format(value);
}

function scoreTone(score: number): string {
  if (score >= 0.35) {
    return "text-[var(--accent-strong)]";
  }
  if (score >= 0.1) {
    return "text-[var(--warning-strong)]";
  }
  return "text-[var(--danger)]";
}

function severityBadgeClass(active: boolean): string {
  return active
    ? "border-[var(--accent-ring)] bg-[var(--accent-soft)] text-[var(--accent-strong)]"
    : "border-[var(--line-soft)] bg-[var(--surface-soft)] text-[var(--muted)]";
}

function topRollingRows(strategy: StrategyAnalyticsRecord): StrategyAnalyticsRecord["rolling20Series"] {
  if (strategy.rolling20Series.length <= 5) {
    return strategy.rolling20Series;
  }
  return strategy.rolling20Series.slice(strategy.rolling20Series.length - 5);
}

function rejectionRows(candidates: StrategyScore[]): StrategyScore[] {
  return candidates.filter((candidate) => !candidate.eligible || candidate.reasons.length > 0);
}

function DataPointRow({
  label,
  value,
  valueClassName
}: {
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-sm leading-6 text-[var(--muted)]">{label}</span>
      <span className={`text-right text-sm font-medium text-[var(--text)] ${valueClassName ?? ""}`}>
        {value}
      </span>
    </div>
  );
}

function MetricCard({
  label,
  value,
  meta,
  valueClassName
}: {
  label: string;
  value: string;
  meta?: string;
  valueClassName?: string;
}) {
  return (
    <article className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <p className="ui-label">{label}</p>
        {meta ? <span className="hidden text-xs font-medium text-[var(--muted)] sm:block">{meta}</span> : null}
      </div>
      <p
        className={`mt-3 text-[1.55rem] font-semibold tracking-[-0.03em] text-[var(--text)] ${valueClassName ?? ""}`}
      >
        {value}
      </p>
    </article>
  );
}

function WorkerDecisionCard({ row }: { row: WorkerSymbolDecision }) {
  return (
    <article className="rounded-[1.25rem] border border-[var(--line-soft)] bg-[var(--panel-soft)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">
              {row.symbol}
            </p>
            <span className="rounded-full border border-[var(--line-soft)] px-2.5 py-1 text-[0.68rem] uppercase tracking-[0.12em] text-[var(--muted)]">
              {row.action}
            </span>
          </div>
          <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
            {row.orderStatus ?? "No order status"} • {row.timeframe}
          </p>
        </div>
        <span className={`rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.12em] ${severityBadgeClass(Boolean(row.selectedStrategy))}`}>
          {row.selectedStrategy ? "Selected" : "Unselected"}
        </span>
      </div>

      <div className="mt-4 grid gap-3 text-sm">
        <DataPointRow label="Active Strategy" value={row.activeStrategy ?? "none"} />
        <DataPointRow label="Latest Selected" value={row.selectedStrategy ?? "none"} />
        <DataPointRow label="Score" value={row.selectedScore.toFixed(4)} />
        <DataPointRow label="No-Trade Reason" value={row.noTradeReason ?? "none"} />
      </div>

      {row.rejectionReasons.length > 0 ? (
        <details className="mt-4 rounded-2xl border border-[var(--line-soft)] bg-[var(--panel)]">
          <summary className="cursor-pointer list-none px-3 py-3 text-sm font-medium text-[var(--text)]">
            Rejection reasons
          </summary>
          <div className="border-t border-[var(--line-soft)] px-3 py-3 text-sm leading-6 text-[var(--muted)]">
            {row.rejectionReasons.join(", ")}
          </div>
        </details>
      ) : null}
    </article>
  );
}

function CandidateCard({ row }: { row: StrategyScore }) {
  return (
    <article className="rounded-[1.25rem] border border-[var(--line-soft)] bg-[var(--panel-soft)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">
            {row.strategy}
          </p>
          <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
            Signal {row.signal.toFixed(3)}
          </p>
        </div>
        <div className="text-right">
          <p className="ui-label">Score</p>
          <p className={`mt-2 text-lg font-semibold tracking-[-0.03em] ${scoreTone(row.score)}`}>
            {row.score.toFixed(4)}
          </p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <div className="rounded-2xl bg-[var(--panel)] px-3 py-3">
          <p className="ui-label">Eligible</p>
          <p className="mt-2 font-semibold text-[var(--text)]">{row.eligible ? "Yes" : "No"}</p>
        </div>
        <div className="rounded-2xl bg-[var(--panel)] px-3 py-3">
          <p className="ui-label">Win Rate</p>
          <p className="mt-2 font-semibold text-[var(--text)]">{formatPct(row.winRate)}</p>
        </div>
      </div>

      <details className="mt-4 rounded-2xl border border-[var(--line-soft)] bg-[var(--panel)]">
        <summary className="cursor-pointer list-none px-3 py-3 text-sm font-medium text-[var(--text)]">
          View model details
        </summary>
        <div className="grid gap-3 border-t border-[var(--line-soft)] px-3 py-3 text-sm">
          <DataPointRow label="Sharpe" value={row.recentSharpe.toFixed(3)} />
          <DataPointRow label="Expectancy" value={formatUsd(row.recentExpectancy)} />
          <DataPointRow label="Regime Fit" value={row.regimeFit.toFixed(2)} />
          <DataPointRow label="Sizing Multiplier" value={row.sizingMultiplier.toFixed(2)} />
          <DataPointRow
            label="Reasons"
            value={row.reasons.length > 0 ? row.reasons.join(", ") : "none"}
          />
        </div>
      </details>
    </article>
  );
}

function StrategyPerformanceCard({
  row,
  includeExpectancy
}: {
  row: StrategyAnalyticsRecord;
  includeExpectancy: boolean;
}) {
  return (
    <article className="rounded-[1.25rem] border border-[var(--line-soft)] bg-[var(--panel-soft)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">
            {row.strategy}
          </p>
          <p className="mt-1 text-xs leading-5 text-[var(--muted)]">{row.numTrades} trades</p>
        </div>
        <div className="text-right">
          <p className="ui-label">Return</p>
          <p className="mt-2 text-lg font-semibold tracking-[-0.03em] text-[var(--text)]">
            {formatPct(row.totalReturn)}
          </p>
        </div>
      </div>

      <details className="mt-4 rounded-2xl border border-[var(--line-soft)] bg-[var(--panel)]">
        <summary className="cursor-pointer list-none px-3 py-3 text-sm font-medium text-[var(--text)]">
          View metrics
        </summary>
        <div className="grid gap-3 border-t border-[var(--line-soft)] px-3 py-3 text-sm">
          <DataPointRow label="Win Rate" value={formatPct(row.winRate)} />
          <DataPointRow label="Profit Factor" value={row.profitFactor.toFixed(2)} />
          {includeExpectancy ? (
            <DataPointRow label="Expectancy" value={formatUsd(row.expectancy)} />
          ) : null}
        </div>
      </details>
    </article>
  );
}

function RollingPointCard({ point }: { point: RollingMetricPoint }) {
  return (
    <article className="rounded-[1.25rem] border border-[var(--line-soft)] bg-[var(--panel-soft)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="ui-label">Trade Window</p>
          <p className="mt-2 text-lg font-semibold tracking-[-0.03em] text-[var(--text)]">
            #{point.tradeIndex}
          </p>
        </div>
        <p className="text-xs leading-5 text-[var(--muted)]">
          {new Date(point.timestamp).toLocaleString()}
        </p>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
        <div className="rounded-2xl bg-[var(--panel)] px-3 py-3">
          <p className="ui-label">Win Rate</p>
          <p className="mt-2 font-semibold text-[var(--text)]">{formatPct(point.winRate)}</p>
        </div>
        <div className="rounded-2xl bg-[var(--panel)] px-3 py-3">
          <p className="ui-label">Expectancy</p>
          <p className="mt-2 font-semibold text-[var(--text)]">{formatUsd(point.expectancy)}</p>
        </div>
        <div className="rounded-2xl bg-[var(--panel)] px-3 py-3">
          <p className="ui-label">Sharpe</p>
          <p className="mt-2 font-semibold text-[var(--text)]">{point.sharpe.toFixed(3)}</p>
        </div>
      </div>
    </article>
  );
}

export default function AnalyticsPage() {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const next = await getAnalyticsData();
        if (!cancelled) {
          setData(next);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Unable to load analytics.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <StatePanel
        title="Loading analytics"
        description="Fetching backtest, paper-trading, selection, and worker analytics."
      />
    );
  }

  if (error || !data) {
    return (
      <StatePanel
        title="Analytics unavailable"
        description={error ?? "Unable to load analytics from backend."}
        tone="danger"
      />
    );
  }

  const paperData = data.paper;
  const backtestData = data.backtest;
  const selectedStrategy = data.selection.selectedStrategy;
  const selectedMetrics = paperData.strategies.strategies.find(
    (row) => row.strategy === selectedStrategy
  );
  const rejected = rejectionRows(data.selection.candidates);
  const backtestAggregationLabel =
    backtestData.strategies.aggregationScope === "multi_run_aggregate"
      ? `Aggregate across ${backtestData.strategies.runCount} persisted backtest runs`
      : backtestData.strategies.runCount === 1
        ? "Single persisted backtest run"
        : "No backtest runs yet";

  return (
    <section className="space-y-4">
      <PageHeader
        eyebrow="Analytics"
        title="Selection & Performance"
        description="Latest selection state first, with deeper execution and performance detail below."
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <MetricCard
          label="Selected Strategy"
          value={selectedStrategy ?? "No strategy selected"}
        />
        <MetricCard
          label="Selection Score"
          value={data.selection.selectedScore.toFixed(4)}
          valueClassName={scoreTone(data.selection.selectedScore)}
        />
        <MetricCard
          label="Worker Dry-Run"
          value={data.execution.dryRunEnabled ? "Enabled" : "Disabled"}
        />
      </div>

      <CollapsibleSection
        title="Execution Analytics"
        description="Worker context, universe coverage, filtered symbols, and the latest symbol-level decisions."
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Worker" value={data.execution.workerName} />
          <MetricCard label="Timeframe" value={data.execution.timeframe} />
          <MetricCard label="Universe Mode" value={data.execution.universeMode} />
          <MetricCard
            label="Last Selected"
            value={
              data.execution.lastSelectedSymbol && data.execution.lastSelectedStrategy
                ? `${data.execution.lastSelectedSymbol} / ${data.execution.lastSelectedStrategy}`
                : "none"
            }
          />
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          <article className="rounded-[1.25rem] border border-[var(--line-soft)] bg-[var(--panel-soft)] p-4">
            <p className="ui-label">Universe Symbols</p>
            <p className="mt-3 text-sm leading-6 text-[var(--text)]">
              {data.execution.universeSymbols.join(", ") || "none"}
            </p>
          </article>
          <article className="rounded-[1.25rem] border border-[var(--line-soft)] bg-[var(--panel-soft)] p-4">
            <p className="ui-label">Scanned / Shortlisted</p>
            <p className="mt-3 text-sm leading-6 text-[var(--text)]">
              Scanned: {data.execution.scannedSymbols.join(", ") || "none"}
            </p>
            <p className="mt-2 text-sm leading-6 text-[var(--text)]">
              Shortlisted: {data.execution.shortlistedSymbols.join(", ") || "none"}
            </p>
            <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
              Last no-trade reason: {data.execution.lastNoTradeReason ?? "none"}
            </p>
          </article>
        </div>

        {Object.keys(data.execution.symbolFilterReasons).length > 0 ? (
          <div className="mt-5">
            <h4 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
              Filtered Symbols
            </h4>

            <div className="mt-3 space-y-3 md:hidden">
              {Object.entries(data.execution.symbolFilterReasons).map(([symbol, reasons]) => (
                <article
                  key={symbol}
                  className="rounded-[1.25rem] border border-[var(--line-soft)] bg-[var(--panel-soft)] p-4"
                >
                  <p className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">
                    {symbol}
                  </p>
                  <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
                    {reasons.length > 0 ? reasons.join(", ") : "none"}
                  </p>
                </article>
              ))}
            </div>

            <div className="hidden md:block">
              <TableScrollArea minWidth={720}>
                <table className="data-table text-sm">
                  <colgroup>
                    <col className="w-[24%]" />
                    <col className="w-[76%]" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>Filtered Symbol</th>
                      <th>Reasons</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(data.execution.symbolFilterReasons).map(([symbol, reasons]) => (
                      <tr key={symbol}>
                        <td>{symbol}</td>
                        <td className="cell-wrap">
                          {reasons.length > 0 ? reasons.join(", ") : "none"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScrollArea>
            </div>
          </div>
        ) : null}

        <div className="mt-5">
          <h4 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
            Symbol Decisions
          </h4>

          {data.execution.symbols.length === 0 ? (
            <p className="mt-3 text-sm text-[var(--muted)]">No execution-cycle data yet.</p>
          ) : (
            <>
              <div className="mt-3 space-y-3 md:hidden">
                {data.execution.symbols.map((row) => (
                  <WorkerDecisionCard key={row.symbol} row={row} />
                ))}
              </div>

              <div className="hidden md:block">
                <TableScrollArea minWidth={1040}>
                  <table className="data-table text-sm">
                    <colgroup>
                      <col className="w-[10%]" />
                      <col className="w-[18%]" />
                      <col className="w-[18%]" />
                      <col className="w-[12%]" />
                      <col className="w-[14%]" />
                      <col className="w-[28%]" />
                    </colgroup>
                    <thead>
                      <tr>
                        <th>Symbol</th>
                        <th>Active Strategy</th>
                        <th>Latest Selected</th>
                        <th>Action</th>
                        <th>Order Status</th>
                        <th>No-Trade Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.execution.symbols.map((row) => (
                        <tr key={row.symbol}>
                          <td>{row.symbol}</td>
                          <td>{row.activeStrategy ?? "none"}</td>
                          <td>{row.selectedStrategy ?? "none"}</td>
                          <td>{row.action}</td>
                          <td>{row.orderStatus ?? "n/a"}</td>
                          <td className="cell-wrap">{row.noTradeReason ?? "none"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableScrollArea>
              </div>
            </>
          )}
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title="Strategy Scores"
        description="Latest scoring snapshot for each strategy candidate, with eligibility and ranking context."
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Current Regime" value={data.selection.regime || "unknown"} />
          <MetricCard
            label="Sizing Multiplier"
            value={`${data.selection.sizingMultiplier.toFixed(2)}x`}
          />
          <MetricCard
            label="Min Score Threshold"
            value={data.selection.minimumScoreThreshold.toFixed(4)}
          />
          <MetricCard
            label="Candidates"
            value={String(data.selection.candidates.length)}
          />
        </div>

        {data.selection.candidates.length === 0 ? (
          <p className="mt-4 text-sm text-[var(--muted)]">No selection-candidate data yet.</p>
        ) : (
          <>
            <div className="mt-4 space-y-3 md:hidden">
              {data.selection.candidates.map((row) => (
                <CandidateCard key={row.strategy} row={row} />
              ))}
            </div>

            <div className="hidden md:block">
              <TableScrollArea minWidth={1060}>
                <table className="data-table text-sm">
                  <colgroup>
                    <col className="w-[22%]" />
                    <col className="w-[9%]" />
                    <col className="w-[9%]" />
                    <col className="w-[9%]" />
                    <col className="w-[10%]" />
                    <col className="w-[10%]" />
                    <col className="w-[14%]" />
                    <col className="w-[10%]" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>Strategy</th>
                      <th className="numeric">Signal</th>
                      <th>Eligible</th>
                      <th className="numeric">Score</th>
                      <th className="numeric">Win Rate</th>
                      <th className="numeric">Sharpe</th>
                      <th className="numeric">Expectancy</th>
                      <th className="numeric">Regime Fit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.selection.candidates.map((row) => (
                      <tr key={row.strategy}>
                        <td>{row.strategy}</td>
                        <td className="numeric">{row.signal.toFixed(3)}</td>
                        <td>{row.eligible ? "yes" : "no"}</td>
                        <td className={`numeric ${scoreTone(row.score)}`}>{row.score.toFixed(4)}</td>
                        <td className="numeric">{formatPct(row.winRate)}</td>
                        <td className="numeric">{row.recentSharpe.toFixed(3)}</td>
                        <td className="numeric">{formatUsd(row.recentExpectancy)}</td>
                        <td className="numeric">{row.regimeFit.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScrollArea>
            </div>
          </>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title="Paper Trading Analytics"
        description={`Source: ${paperData.strategies.dataSource}`}
      >
        {paperData.strategies.strategies.length === 0 ? (
          <p className="text-sm text-[var(--muted)]">No paper execution fills yet.</p>
        ) : (
          <>
            <div className="space-y-3 md:hidden">
              {paperData.strategies.strategies.map((row) => (
                <StrategyPerformanceCard
                  key={row.strategy}
                  row={row}
                  includeExpectancy
                />
              ))}
            </div>

            <div className="hidden md:block">
              <TableScrollArea minWidth={840}>
                <table className="data-table text-sm">
                  <colgroup>
                    <col className="w-[30%]" />
                    <col className="w-[10%]" />
                    <col className="w-[14%]" />
                    <col className="w-[14%]" />
                    <col className="w-[16%]" />
                    <col className="w-[16%]" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>Strategy</th>
                      <th className="numeric">Trades</th>
                      <th className="numeric">Total Return</th>
                      <th className="numeric">Win Rate</th>
                      <th className="numeric">Profit Factor</th>
                      <th className="numeric">Expectancy</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paperData.strategies.strategies.map((row) => (
                      <tr key={row.strategy}>
                        <td>{row.strategy}</td>
                        <td className="numeric">{row.numTrades}</td>
                        <td className="numeric">{formatPct(row.totalReturn)}</td>
                        <td className="numeric">{formatPct(row.winRate)}</td>
                        <td className="numeric">{row.profitFactor.toFixed(2)}</td>
                        <td className="numeric">{formatUsd(row.expectancy)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScrollArea>
            </div>
          </>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title="Backtest Analytics"
        description={`Source: ${backtestData.strategies.dataSource}. ${backtestAggregationLabel}.`}
      >
        {backtestData.strategies.strategies.length === 0 ? (
          <p className="text-sm text-[var(--muted)]">No persisted backtest runs yet.</p>
        ) : (
          <>
            <div className="space-y-3 md:hidden">
              {backtestData.strategies.strategies.map((row) => (
                <StrategyPerformanceCard
                  key={`${row.strategy}-backtest`}
                  row={row}
                  includeExpectancy={false}
                />
              ))}
            </div>

            <div className="hidden md:block">
              <TableScrollArea minWidth={760}>
                <table className="data-table text-sm">
                  <colgroup>
                    <col className="w-[36%]" />
                    <col className="w-[12%]" />
                    <col className="w-[17%]" />
                    <col className="w-[17%]" />
                    <col className="w-[18%]" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>Strategy</th>
                      <th className="numeric">Trades</th>
                      <th className="numeric">Total Return</th>
                      <th className="numeric">Win Rate</th>
                      <th className="numeric">Profit Factor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {backtestData.strategies.strategies.map((row) => (
                      <tr key={`${row.strategy}-backtest`}>
                        <td>{row.strategy}</td>
                        <td className="numeric">{row.numTrades}</td>
                        <td className="numeric">{formatPct(row.totalReturn)}</td>
                        <td className="numeric">{formatPct(row.winRate)}</td>
                        <td className="numeric">{row.profitFactor.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScrollArea>
            </div>
          </>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title="Rolling 20-Trade Snapshot"
        description="Latest rolling paper-trading window for the currently selected strategy."
      >
        {selectedMetrics == null ? (
          <p className="text-sm text-[var(--muted)]">
            No selected paper strategy rolling data yet.
          </p>
        ) : (
          <>
            <div className="space-y-3 md:hidden">
              {topRollingRows(selectedMetrics).map((point) => (
                <RollingPointCard
                  key={`${point.tradeIndex}-${point.timestamp}`}
                  point={point}
                />
              ))}
            </div>

            <div className="hidden md:block">
              <TableScrollArea minWidth={860}>
                <table className="data-table text-sm">
                  <colgroup>
                    <col className="w-[12%]" />
                    <col className="w-[33%]" />
                    <col className="w-[17%]" />
                    <col className="w-[20%]" />
                    <col className="w-[18%]" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th className="numeric">Trade #</th>
                      <th>Timestamp</th>
                      <th className="numeric">Win Rate</th>
                      <th className="numeric">Expectancy</th>
                      <th className="numeric">Sharpe</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topRollingRows(selectedMetrics).map((point) => (
                      <tr key={`${point.tradeIndex}-${point.timestamp}`}>
                        <td className="numeric">{point.tradeIndex}</td>
                        <td>{new Date(point.timestamp).toLocaleString()}</td>
                        <td className="numeric">{formatPct(point.winRate)}</td>
                        <td className="numeric">{formatUsd(point.expectancy)}</td>
                        <td className="numeric">{point.sharpe.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScrollArea>
            </div>
          </>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title="Strategy Rejections / Deprioritization"
        description="Candidates that were rejected outright or ranked below the current selection."
      >
        {rejected.length === 0 ? (
          <p className="text-sm text-[var(--muted)]">No rejected strategies in the latest decision.</p>
        ) : (
          <>
            <div className="space-y-3 md:hidden">
              {rejected.map((row) => (
                <article
                  key={row.strategy}
                  className="rounded-[1.25rem] border border-[var(--line-soft)] bg-[var(--panel-soft)] p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">
                      {row.strategy}
                    </p>
                    <p className={`text-lg font-semibold tracking-[-0.03em] ${scoreTone(row.score)}`}>
                      {row.score.toFixed(4)}
                    </p>
                  </div>
                  <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
                    {row.reasons.length > 0 ? row.reasons.join(", ") : "deprioritized"}
                  </p>
                </article>
              ))}
            </div>

            <div className="hidden md:block">
              <TableScrollArea minWidth={860}>
                <table className="data-table text-sm">
                  <colgroup>
                    <col className="w-[24%]" />
                    <col className="w-[14%]" />
                    <col className="w-[62%]" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>Strategy</th>
                      <th className="numeric">Score</th>
                      <th>Reasons</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rejected.map((row) => (
                      <tr key={row.strategy}>
                        <td>{row.strategy}</td>
                        <td className="numeric">{row.score.toFixed(4)}</td>
                        <td className="cell-wrap">
                          {row.reasons.length > 0 ? row.reasons.join(", ") : "deprioritized"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScrollArea>
            </div>
          </>
        )}
      </CollapsibleSection>
    </section>
  );
}
