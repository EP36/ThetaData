"use client";

import { useEffect, useState } from "react";

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
      <section className="glass-panel rounded-3xl p-5 text-sm text-[var(--muted)]">
        Loading analytics...
      </section>
    );
  }

  if (error || !data) {
    return (
      <section className="glass-panel rounded-3xl p-5">
        <h2 className="page-title font-semibold">Analytics & Selection</h2>
        <p className="mt-2 text-sm text-[var(--danger)]">
          {error ?? "Unable to load analytics from backend."}
        </p>
      </section>
    );
  }

  const selectedStrategy = data.selection.selectedStrategy;
  const selectedMetrics = data.strategies.strategies.find(
    (row) => row.strategy === selectedStrategy
  );
  const rejected = rejectionRows(data.selection.candidates);

  return (
    <section className="space-y-4">
      <div className="glass-panel rounded-3xl p-4 md:px-5 md:py-5">
        <h2 className="page-title font-semibold">Analytics & Selection</h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Strategy scoring, regime state, and allocation decisions from real persisted data.
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
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
      </div>

      <article className="glass-panel rounded-2xl p-4">
        <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
          Strategy Scores
        </h3>
        {data.selection.candidates.length === 0 ? (
          <p className="mt-3 text-sm text-[var(--muted)]">No trading data yet.</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="data-table text-sm">
              <thead>
                <tr>
                  <th>Strategy</th>
                  <th>Signal</th>
                  <th>Eligible</th>
                  <th>Score</th>
                  <th>Win Rate</th>
                  <th>Sharpe</th>
                  <th>Expectancy</th>
                  <th>Regime Fit</th>
                </tr>
              </thead>
              <tbody>
                {data.selection.candidates.map((row) => (
                  <tr key={row.strategy}>
                    <td>{row.strategy}</td>
                    <td>{row.signal.toFixed(3)}</td>
                    <td>{row.eligible ? "yes" : "no"}</td>
                    <td className={scoreTone(row.score)}>{row.score.toFixed(4)}</td>
                    <td>{formatPct(row.winRate)}</td>
                    <td>{row.recentSharpe.toFixed(3)}</td>
                    <td>{formatUsd(row.recentExpectancy)}</td>
                    <td>{row.regimeFit.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>

      <div className="grid gap-4 xl:grid-cols-2">
        <article className="glass-panel rounded-2xl p-4">
          <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
            Strategy Analytics Summary
          </h3>
          {data.strategies.strategies.length === 0 ? (
            <p className="mt-3 text-sm text-[var(--muted)]">No trading data yet.</p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="data-table text-sm">
                <thead>
                  <tr>
                    <th>Strategy</th>
                    <th>Trades</th>
                    <th>Total Return</th>
                    <th>Win Rate</th>
                    <th>Profit Factor</th>
                    <th>Expectancy</th>
                    <th>Max DD</th>
                    <th>Avg Hold</th>
                  </tr>
                </thead>
                <tbody>
                  {data.strategies.strategies.map((row) => (
                    <tr key={row.strategy}>
                      <td>{row.strategy}</td>
                      <td>{row.numTrades}</td>
                      <td>{formatPct(row.totalReturn)}</td>
                      <td>{formatPct(row.winRate)}</td>
                      <td>{row.profitFactor.toFixed(2)}</td>
                      <td>{formatUsd(row.expectancy)}</td>
                      <td>{formatPct(row.maxDrawdown)}</td>
                      <td>{row.averageHoldTimeHours.toFixed(2)}h</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>

        <article className="glass-panel rounded-2xl p-4">
          <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
            Rolling 20-Trade Performance
          </h3>
          {selectedMetrics == null ? (
            <p className="mt-3 text-sm text-[var(--muted)]">No selected strategy with rolling data yet.</p>
          ) : (
            <>
              <p className="mt-2 text-sm text-[var(--muted)]">
                Latest rolling metrics for <strong>{selectedMetrics.strategy}</strong>
              </p>
              <div className="mt-3 overflow-x-auto">
                <table className="data-table text-sm">
                  <thead>
                    <tr>
                      <th>Trade #</th>
                      <th>Timestamp</th>
                      <th>Win Rate</th>
                      <th>Expectancy</th>
                      <th>Sharpe</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topRollingRows(selectedMetrics).map((point) => (
                      <tr key={`${point.tradeIndex}-${point.timestamp}`}>
                        <td>{point.tradeIndex}</td>
                        <td>{new Date(point.timestamp).toLocaleString()}</td>
                        <td>{formatPct(point.winRate)}</td>
                        <td>{formatUsd(point.expectancy)}</td>
                        <td>{point.sharpe.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </article>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <article className="glass-panel rounded-2xl p-4">
          <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
            Strategy Rejections / Deprioritization
          </h3>
          {rejected.length === 0 ? (
            <p className="mt-3 text-sm text-[var(--muted)]">No rejected strategies in the latest decision.</p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="data-table text-sm">
                <thead>
                  <tr>
                    <th>Strategy</th>
                    <th>Score</th>
                    <th>Reasons</th>
                  </tr>
                </thead>
                <tbody>
                  {rejected.map((row) => (
                    <tr key={row.strategy}>
                      <td>{row.strategy}</td>
                      <td>{row.score.toFixed(4)}</td>
                      <td>{row.reasons.length > 0 ? row.reasons.join(", ") : "deprioritized"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>

        <article className="glass-panel rounded-2xl p-4">
          <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
            Portfolio Contribution by Strategy
          </h3>
          {data.portfolio.strategyContribution.length === 0 ? (
            <p className="mt-3 text-sm text-[var(--muted)]">No realized strategy contribution yet.</p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="data-table text-sm">
                <thead>
                  <tr>
                    <th>Strategy</th>
                    <th>Trades</th>
                    <th>Realized PnL</th>
                    <th>Return %</th>
                  </tr>
                </thead>
                <tbody>
                  {data.portfolio.strategyContribution.map((row) => (
                    <tr key={row.strategy}>
                      <td>{row.strategy}</td>
                      <td>{row.trades}</td>
                      <td>{formatUsd(row.realizedPnl)}</td>
                      <td>{formatPct(row.returnPct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <article className="glass-panel rounded-2xl p-4">
          <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
            Context Performance by Symbol
          </h3>
          {data.context.bySymbol.length === 0 ? (
            <p className="mt-3 text-sm text-[var(--muted)]">No trading data yet.</p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="data-table text-sm">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Trades</th>
                    <th>Win Rate</th>
                    <th>Expectancy</th>
                    <th>Total PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {data.context.bySymbol.map((row) => (
                    <tr key={row.key}>
                      <td>{row.key}</td>
                      <td>{row.trades}</td>
                      <td>{formatPct(row.winRate)}</td>
                      <td>{formatUsd(row.expectancy)}</td>
                      <td>{formatUsd(row.totalPnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>

        <article className="glass-panel rounded-2xl p-4">
          <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
            Context Performance by Regime
          </h3>
          {data.context.byRegime.length === 0 ? (
            <p className="mt-3 text-sm text-[var(--muted)]">No regime-tagged trade history yet.</p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="data-table text-sm">
                <thead>
                  <tr>
                    <th>Regime</th>
                    <th>Trades</th>
                    <th>Win Rate</th>
                    <th>Expectancy</th>
                    <th>Total PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {data.context.byRegime.map((row) => (
                    <tr key={row.key}>
                      <td>{row.key}</td>
                      <td>{row.trades}</td>
                      <td>{formatPct(row.winRate)}</td>
                      <td>{formatUsd(row.expectancy)}</td>
                      <td>{formatUsd(row.totalPnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      </div>
    </section>
  );
}
