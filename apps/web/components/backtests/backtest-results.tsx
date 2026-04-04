import { EquityDrawdownCharts } from "@/components/dashboard/equity-drawdown-charts";
import { RecentTradesTable } from "@/components/dashboard/recent-trades-table";
import type { BacktestResultData } from "@/lib/types";

type BacktestResultsProps = {
  result: BacktestResultData;
};

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

export function BacktestResults({ result }: BacktestResultsProps) {
  const metricRows = [
    { label: "Total Return", value: formatPct(result.metrics.totalReturn) },
    { label: "Sharpe", value: result.metrics.sharpe.toFixed(2) },
    { label: "Max Drawdown", value: formatPct(result.metrics.maxDrawdown) },
    { label: "Win Rate", value: formatPct(result.metrics.winRate) },
    { label: "Profit Factor", value: result.metrics.profitFactor.toFixed(2) },
    { label: "Risk Per Trade", value: formatUsd(result.metrics.riskPerTrade) },
    { label: "Risk Per Trade %", value: formatPct(result.metrics.riskPerTradePct) },
    { label: "Position Size %", value: formatPct(result.metrics.positionSizePct) }
  ];

  return (
    <section className="space-y-4">
      <div className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
        <h3 className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">
          Summary Metrics
        </h3>
        <p className="mt-1 text-sm leading-6 text-[var(--muted)]">
          High-level quality indicators for the most recent backtest run.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-4">
          {metricRows.map((metric, idx) => (
            <article
              key={metric.label}
              className="panel-animate rounded-[1.2rem] border border-[var(--line-soft)] bg-[var(--panel-soft)] p-4"
              style={{ animationDelay: `${idx * 60}ms` }}
            >
              <p className="ui-label">
                {metric.label}
              </p>
              <p className="mt-3 text-xl font-semibold tracking-[-0.03em]">{metric.value}</p>
            </article>
          ))}
        </div>
      </div>

      <EquityDrawdownCharts
        equityCurve={result.equityCurve}
        drawdownCurve={result.drawdownCurve}
      />

      <div className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
        <RecentTradesTable trades={result.trades} title="Backtest Trades" />
      </div>
    </section>
  );
}
