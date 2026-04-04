"use client";

import { useEffect, useState } from "react";

import { RiskEventsTable } from "@/components/risk/risk-events-table";
import { RiskMetricCard } from "@/components/risk/risk-metric-card";
import { PageHeader } from "@/components/ui/page-header";
import { StatePanel } from "@/components/ui/state-panel";
import {
  getRiskEvents,
  getRiskStatus,
  setEmergencyStop
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
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadRiskData() {
      setLoading(true);
      setLoadError(null);
      try {
        const [riskStatus, riskEvents] = await Promise.all([
          getRiskStatus(),
          getRiskEvents()
        ]);
        if (!cancelled) {
          setStatus(riskStatus);
          setEvents(riskEvents);
        }
      } catch (error) {
        if (!cancelled) {
          setLoadError(
            error instanceof Error && error.message
              ? error.message
              : "Unable to load risk state."
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadRiskData();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleEmergencyStop = async () => {
    if (!status) {
      return;
    }
    const enableKillSwitch = !status.killSwitchEnabled;
    if (!enableKillSwitch) {
      const confirmed = window.confirm(
        "Disable Emergency Stop and allow the worker to resume paper-trading activity?"
      );
      if (!confirmed) {
        return;
      }
    }

    const previousStatus = status;
    setActionError(null);
    setIsTriggeringStop(true);
    setStatus({ ...status, killSwitchEnabled: enableKillSwitch });
    try {
      const nextStatus = await setEmergencyStop(enableKillSwitch);
      const nextEvents = await getRiskEvents();
      setStatus(nextStatus);
      setEvents(nextEvents);
    } catch (error) {
      setStatus(previousStatus);
      setActionError(
        error instanceof Error && error.message
          ? error.message
          : "Unable to update kill switch state."
      );
    } finally {
      setIsTriggeringStop(false);
    }
  };

  if (loading) {
    return (
      <StatePanel
        title="Loading risk state"
        description="Fetching limits, rejected orders, and emergency-stop status."
      />
    );
  }
  if (loadError || !status) {
    return (
      <StatePanel
        title="Risk state unavailable"
        description={loadError ?? "Unable to load risk state."}
        tone="danger"
      />
    );
  }

  const drawdownTone = status.currentDrawdown > 0.02 ? "warning" : "neutral";
  const killTone = status.killSwitchEnabled ? "critical" : "neutral";
  const killSwitchIndicatorClass = status.killSwitchEnabled
    ? "border-[var(--danger)] bg-[color:color-mix(in_srgb,var(--danger),white_90%)] text-[var(--danger)]"
    : "border-[var(--accent-ring)] bg-[var(--accent-soft)] text-[var(--accent-strong)]";
  const killSwitchMessage = status.killSwitchEnabled
    ? "Emergency stop is ON. New paper orders should be blocked until this is disabled."
    : "Emergency stop is OFF. Controls are in normal operating mode.";

  return (
    <section className="space-y-4">
      <PageHeader
        eyebrow="Risk"
        title="Risk Operations"
        description="Monitor limits, rejected orders, and emergency controls."
        meta={
          <span className={`ui-pill ${killSwitchIndicatorClass}`}>
            {status.killSwitchEnabled ? "Emergency Stop ON" : "Emergency Stop OFF"}
          </span>
        }
      />

      <div className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-sm leading-6 text-[var(--muted)]">{killSwitchMessage}</p>
          </div>
          <button
            type="button"
            onClick={handleEmergencyStop}
            disabled={isTriggeringStop}
            className={`ui-button ${
              status.killSwitchEnabled ? "ui-button-primary" : "ui-button-danger"
            } w-full lg:w-auto`}
          >
            {isTriggeringStop
              ? "Updating..."
              : status.killSwitchEnabled
                ? "Disable Emergency Stop"
                : "Activate Emergency Stop"}
          </button>
        </div>
        {actionError ? (
          <p className="mt-3 rounded-xl border border-[var(--danger)] bg-[color:color-mix(in_srgb,var(--danger),white_92%)] px-3 py-2 text-sm text-[var(--danger)]">
            {actionError}
          </p>
        ) : null}
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

      <article className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
        <h3 className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">
          Rejected Order Reasons
        </h3>
        {status.rejectedOrders.length === 0 ? (
          <p className="mt-3 text-sm text-[var(--muted)]">No rejected orders.</p>
        ) : (
          <ul className="mt-4 space-y-3">
            {status.rejectedOrders.map((reason) => (
              <li
                key={reason}
                className="rounded-[1.1rem] bg-[var(--panel-soft)] px-4 py-3 text-sm leading-6"
              >
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
