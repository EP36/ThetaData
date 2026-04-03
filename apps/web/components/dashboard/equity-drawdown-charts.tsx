"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

import type { TimeSeriesPoint } from "@/lib/types";

type EquityDrawdownChartsProps = {
  equityCurve: TimeSeriesPoint[];
  drawdownCurve: TimeSeriesPoint[];
};

function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0
  }).format(value);
}

function formatPct(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

export function EquityDrawdownCharts({
  equityCurve,
  drawdownCurve
}: EquityDrawdownChartsProps) {
  const hasEquity = equityCurve.length > 0;
  const hasDrawdown = drawdownCurve.length > 0;

  return (
    <section className="grid gap-4 lg:grid-cols-2">
      <article className="glass-panel rounded-3xl p-4">
        <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
          Equity Curve
        </h3>
        <div className="mt-3 h-64 w-full">
          {!hasEquity ? (
            <div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">
              No persisted equity curve yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={equityCurve}>
                <defs>
                  <linearGradient id="equityStroke" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="var(--accent)" />
                    <stop offset="100%" stopColor="var(--accent-strong)" />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  vertical={false}
                  strokeDasharray="4 4"
                  stroke="var(--chart-grid)"
                />
                <XAxis
                  dataKey="timestamp"
                  tick={{ fontSize: 12, fill: "var(--muted)" }}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  tickFormatter={formatCurrency}
                  tick={{ fontSize: 12, fill: "var(--muted)" }}
                  width={80}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  contentStyle={{
                    borderRadius: "0.8rem",
                    border: "1px solid var(--line-strong)",
                    background: "var(--tooltip-bg)",
                    color: "var(--text)",
                    boxShadow: "var(--tooltip-shadow)"
                  }}
                  labelStyle={{ color: "var(--muted)" }}
                  itemStyle={{ color: "var(--text)" }}
                  formatter={(value: number) => formatCurrency(value)}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="url(#equityStroke)"
                  strokeWidth={2.8}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </article>

      <article className="glass-panel rounded-3xl p-4">
        <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
          Drawdown
        </h3>
        <div className="mt-3 h-64 w-full">
          {!hasDrawdown ? (
            <div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">
              No persisted drawdown curve yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={drawdownCurve}>
                <CartesianGrid
                  vertical={false}
                  strokeDasharray="4 4"
                  stroke="var(--chart-grid)"
                />
                <XAxis
                  dataKey="timestamp"
                  tick={{ fontSize: 12, fill: "var(--muted)" }}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  tickFormatter={formatPct}
                  tick={{ fontSize: 12, fill: "var(--muted)" }}
                  width={70}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  contentStyle={{
                    borderRadius: "0.8rem",
                    border: "1px solid var(--line-strong)",
                    background: "var(--tooltip-bg)",
                    color: "var(--text)",
                    boxShadow: "var(--tooltip-shadow)"
                  }}
                  labelStyle={{ color: "var(--muted)" }}
                  itemStyle={{ color: "var(--text)" }}
                  formatter={(value: number) => formatPct(value)}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="var(--danger)"
                  strokeWidth={2.6}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </article>
    </section>
  );
}
