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
  return (
    <section className="grid gap-4 lg:grid-cols-2">
      <article className="glass-panel rounded-3xl p-4">
        <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
          Equity Curve
        </h3>
        <div className="mt-3 h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={equityCurve}>
              <defs>
                <linearGradient id="equityStroke" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#00c805" />
                  <stop offset="100%" stopColor="#00a403" />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} strokeDasharray="4 4" stroke="rgba(16, 25, 35, 0.08)" />
              <XAxis dataKey="timestamp" tick={{ fontSize: 12, fill: "#617085" }} tickLine={false} axisLine={false} />
              <YAxis tickFormatter={formatCurrency} tick={{ fontSize: 12, fill: "#617085" }} width={80} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{
                  borderRadius: "0.8rem",
                  border: "1px solid rgba(16, 25, 35, 0.12)",
                  boxShadow: "0 12px 24px rgba(16, 25, 35, 0.12)"
                }}
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
        </div>
      </article>

      <article className="glass-panel rounded-3xl p-4">
        <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
          Drawdown
        </h3>
        <div className="mt-3 h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={drawdownCurve}>
              <CartesianGrid vertical={false} strokeDasharray="4 4" stroke="rgba(16, 25, 35, 0.08)" />
              <XAxis dataKey="timestamp" tick={{ fontSize: 12, fill: "#617085" }} tickLine={false} axisLine={false} />
              <YAxis tickFormatter={formatPct} tick={{ fontSize: 12, fill: "#617085" }} width={70} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{
                  borderRadius: "0.8rem",
                  border: "1px solid rgba(16, 25, 35, 0.12)",
                  boxShadow: "0 12px 24px rgba(16, 25, 35, 0.12)"
                }}
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
        </div>
      </article>
    </section>
  );
}
