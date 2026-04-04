"use client";

import { useEffect, useState } from "react";

import { TableScrollArea } from "@/components/table/table-scroll-area";
import { getAnalyticsData } from "@/lib/analytics/service";
import type { AnalyticsData } from "@/lib/analytics/service";
import type { StrategyAnalyticsRecord, StrategyScore } from "@/lib/types";

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
    return "text-[var(--warning)]";
  }
  return "text-[var(--danger)]";
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
      <section className="glass-panel rounded-2xl p-4 text-sm text-[var(--muted)]">
        Loading analytics...
      </section>
    );
  }

  if (error || !data) {
    return (
      <section className="glass-panel rounded-2xl p-4">
        <h2 className="page-title font-semibold">Analytics & Selection</h2>
        <p className="mt-2 text-sm text-[var(--danger)]">
          {error ?? "Unable to load analytics from backend."}
        </p>
      </section>
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
      <div className="px-1">
        <h2 className="page-title font-semibold">Analytics & Selection</h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Source-separated analytics for backtests, execution flow, and paper-trading performance.
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <article className="glass-panel rounded-2xl p-4">
          <p className="ui-label">Current Regime</p>
          <p className="mt-1 text-lg font-semibold">{data.selection.regime || "unknown"}</p>
        </article>
        <article className="glass-panel rounded-2xl p-4">
          <p className="ui-label">Selected Strategy</p>
          <p className="mt-1 text-lg font-semibold">{selectedStrategy ?? "No strategy selected"}</p>
        </article>
        <article className="glass-panel rounded-2xl p-4">
          <p className="ui-label">Selection Score</p>
          <p className={`mt-1 text-lg font-semibold ${scoreTone(data.selection.selectedScore)}`}>
            {data.selection.selectedScore.toFixed(4)}
          </p>
        </article>
        <article className="glass-panel rounded-2xl p-4">
          <p className="ui-label">Sizing Multiplier</p>
          <p className="mt-1 text-lg font-semibold">{data.selection.sizingMultiplier.toFixed(2)}x</p>
        </article>
        <article className="glass-panel rounded-2xl p-4">
          <p className="ui-label">Worker Dry-Run</p>
          <p className="mt-1 text-lg font-semibold">
            {data.execution.dryRunEnabled ? "Enabled" : "Disabled"}
          </p>
        </article>
      </div>

      <article className="glass-panel rounded-2xl p-4">
        <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
          Execution Analytics (Worker)
        </h3>
        <p className="mt-2 text-sm text-[var(--muted)]">
          Worker <strong>{data.execution.workerName}</strong> on timeframe <strong>{data.execution.timeframe}</strong>. Mode: <strong>{data.execution.universeMode}</strong>. Universe: <strong>{data.execution.universeSymbols.join(", ") || "none"}</strong>. Scanned: <strong>{data.execution.scannedSymbols.join(", ") || "none"}</strong>. Shortlisted: <strong>{data.execution.shortlistedSymbols.join(", ") || "none"}</strong>. Last selected: <strong>{data.execution.lastSelectedSymbol ?? "none"} / {data.execution.lastSelectedStrategy ?? "none"}</strong>. Last no-trade reason: <strong>{data.execution.lastNoTradeReason ?? "none"}</strong>.
        </p>
        {Object.keys(data.execution.symbolFilterReasons).length > 0 ? (
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
                    <td className="cell-wrap">{reasons.length > 0 ? reasons.join(", ") : "none"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScrollArea>
        ) : null}
        {data.execution.symbols.length === 0 ? (
          <p className="mt-3 text-sm text-[var(--muted)]">No execution-cycle data yet.</p>
        ) : (
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
        )}
      </article>

      <article className="glass-panel rounded-2xl p-4">
        <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
          Strategy Scores
        </h3>
        {data.selection.candidates.length === 0 ? (
          <p className="mt-3 text-sm text-[var(--muted)]">No selection-candidate data yet.</p>
        ) : (
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
        )}
      </article>

      <div className="grid gap-4 xl:grid-cols-2">
        <article className="glass-panel rounded-2xl p-4">
          <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
            Paper Trading Analytics
          </h3>
          <p className="mt-2 text-xs text-[var(--muted)]">
            Source: <strong>{paperData.strategies.dataSource}</strong>
          </p>
          {paperData.strategies.strategies.length === 0 ? (
            <p className="mt-3 text-sm text-[var(--muted)]">No paper execution fills yet.</p>
          ) : (
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
          )}
        </article>

        <article className="glass-panel rounded-2xl p-4">
          <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
            Backtest Analytics
          </h3>
          <p className="mt-2 text-xs text-[var(--muted)]">
            Source: <strong>{backtestData.strategies.dataSource}</strong>
          </p>
          <p className="mt-1 text-xs text-[var(--muted)]">
            Scope: <strong>{backtestAggregationLabel}</strong>. For per-run results, use the
            Backtests page run output.
          </p>
          {backtestData.strategies.strategies.length === 0 ? (
            <p className="mt-3 text-sm text-[var(--muted)]">No persisted backtest runs yet.</p>
          ) : (
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
          )}
        </article>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <article className="glass-panel rounded-2xl p-4">
        <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
          Rolling 20-Trade (Paper)
        </h3>
        {selectedMetrics == null ? (
          <p className="mt-3 text-sm text-[var(--muted)]">No selected paper strategy rolling data yet.</p>
        ) : (
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
        )}
      </article>

        <article className="glass-panel rounded-2xl p-4">
        <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
          Strategy Rejections / Deprioritization
        </h3>
        {rejected.length === 0 ? (
          <p className="mt-3 text-sm text-[var(--muted)]">No rejected strategies in the latest decision.</p>
        ) : (
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
        )}
      </article>
      </div>
    </section>
  );
}
