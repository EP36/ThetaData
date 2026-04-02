"use client";

import { useEffect, useState } from "react";

import { RiskEventsTable } from "@/components/risk/risk-events-table";
import { RiskMetricCard } from "@/components/risk/risk-metric-card";
import {
  getRiskEvents,
  getRiskStatus,
  triggerEmergencyStop
} from "@/lib/risk/service";
import type { RiskEvent, RiskStatusData } from "@/lib/types";

function formatUsd(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0
  }).format(value);
}

function formatPct(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

export default function RiskPage() {
  const [status, setStatus] = useState<RiskStatusData | null>(null);
  const [events, setEvents] = useState<RiskEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [isTriggeringStop, setIsTriggeringStop] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadRiskData() {
      setLoading(true);
      const [riskStatus, riskEvents] = await Promise.all([
        getRiskStatus(),
        getRiskEvents()
      ]);
      if (!cancelled) {
        setStatus(riskStatus);
        setEvents(riskEvents);
        setLoading(false);
      }
    }

    void loadRiskData();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleEmergencyStop = async () => {
    setIsTriggeringStop(true);
    const nextStatus = await triggerEmergencyStop();
    const nextEvents = await getRiskEvents();
    setStatus(nextStatus);
    setEvents(nextEvents);
    setIsTriggeringStop(false);
  };

  if (loading || !status) {
    return (
      <section className="glass-panel rounded-3xl p-6">
        <h2 className="page-title font-semibold">Risk</h2>
        <p className="mt-2 text-sm text-[var(--muted)]">Loading risk state...</p>
      </section>
    );
  }

  const drawdownTone = status.currentDrawdown > 0.02 ? "warning" : "neutral";
  const killTone = status.killSwitchEnabled ? "critical" : "neutral";

  return (
    <section className="space-y-4">
      <div className="glass-panel rounded-3xl p-4 md:px-5 md:py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="page-title font-semibold">Risk Operations</h2>
            <p className="mt-1 text-sm text-[var(--muted)]">
              Monitor limits, rejected orders, and emergency controls.
            </p>
          </div>
          <button
            type="button"
            onClick={handleEmergencyStop}
            disabled={isTriggeringStop || status.killSwitchEnabled}
            className="ui-button ui-button-danger"
          >
            {status.killSwitchEnabled
              ? "Emergency Stop Active"
              : isTriggeringStop
                ? "Stopping..."
                : "Emergency Stop"}
          </button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <RiskMetricCard label="Max Daily Loss" value={formatUsd(status.maxDailyLoss)} />
        <RiskMetricCard
          label="Current Drawdown"
          value={formatPct(status.currentDrawdown)}
          tone={drawdownTone}
        />
        <RiskMetricCard
          label="Max Position Size"
          value={formatPct(status.maxPositionSize)}
        />
        <RiskMetricCard
          label="Gross Exposure"
          value={formatPct(status.grossExposure)}
        />
        <RiskMetricCard
          label="Kill Switch"
          value={status.killSwitchEnabled ? "Enabled" : "Disabled"}
          tone={killTone}
        />
        <RiskMetricCard
          label="Rejected Orders"
          value={String(status.rejectedOrders.length)}
          tone={status.rejectedOrders.length > 0 ? "warning" : "neutral"}
        />
      </div>

      <article className="glass-panel rounded-2xl p-4">
        <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
          Rejected Order Reasons
        </h3>
        {status.rejectedOrders.length === 0 ? (
          <p className="mt-2 text-sm text-[var(--muted)]">No rejected orders.</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {status.rejectedOrders.map((reason) => (
              <li key={reason} className="rounded-lg bg-[var(--panel-soft)] px-3 py-2 text-sm">
                {reason}
              </li>
            ))}
          </ul>
        )}
      </article>

      <RiskEventsTable events={events} />
    </section>
  );
}
