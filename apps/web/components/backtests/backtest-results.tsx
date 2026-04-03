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
      <div className="glass-panel rounded-3xl p-4 md:px-5">
        <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
          Summary Metrics
        </h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
          {metricRows.map((metric, idx) => (
            <article
              key={metric.label}
              className="panel-animate rounded-xl border border-[rgba(16,25,35,0.08)] bg-[var(--panel-soft)] p-3"
              style={{ animationDelay: `${idx * 60}ms` }}
            >
              <p className="text-xs uppercase tracking-[0.12em] text-[var(--muted)]">
                {metric.label}
              </p>
              <p className="mt-1 text-lg font-semibold">{metric.value}</p>
            </article>
          ))}
        </div>
      </div>

      <EquityDrawdownCharts
        equityCurve={result.equityCurve}
        drawdownCurve={result.drawdownCurve}
      />

      <RecentTradesTable trades={result.trades} />
    </section>
  );
}
