"use client";

import { useEffect, useState } from "react";

import { StrategyCard } from "@/components/strategies/strategy-card";
import { PageHeader } from "@/components/ui/page-header";
import { StatePanel } from "@/components/ui/state-panel";
import {
  getPaperTradingEnabled,
  getStrategies,
  setPaperTradingEnabled,
  updateStrategy
} from "@/lib/strategies/service";
import { isDemoModeEnabled } from "@/lib/runtime/demo-mode";
import type { StrategyConfig, StrategyValidationErrors } from "@/lib/types";

export default function StrategiesPage() {
  const demoModeEnabled = isDemoModeEnabled();
  const [strategies, setStrategies] = useState<StrategyConfig[]>([]);
  const [paperTradingEnabled, setPaperTrading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadPageData() {
      setLoading(true);
      const [strategyRows, paperStatus] = await Promise.all([
        getStrategies(),
        getPaperTradingEnabled()
      ]);
      if (!cancelled) {
        setStrategies(strategyRows);
        setPaperTrading(paperStatus);
        setLoading(false);
      }
    }

    void loadPageData();
    return () => {
      cancelled = true;
    };
  }, []);

  const handlePaperToggle = async () => {
    const next = await setPaperTradingEnabled(!paperTradingEnabled);
    setPaperTrading(next);
    setMessage(
      next
        ? "Paper trading enabled for mock operations."
        : "Paper trading disabled (default-safe mode)."
    );
  };

  const handleSaveStrategy = async (
    strategyName: StrategyConfig["name"],
    payload: Partial<Pick<StrategyConfig, "status" | "parameters">>
  ): Promise<StrategyValidationErrors> => {
    const result = await updateStrategy(strategyName, payload);
    const updatedStrategy = result.strategy;
    if (updatedStrategy) {
      setStrategies((previous) =>
        previous.map((item) => (item.name === strategyName ? updatedStrategy : item))
      );
      setMessage(`Saved ${strategyName} settings.`);
      return {};
    }
    return result.errors;
  };

  return (
    <section className="space-y-5">
      <PageHeader
        eyebrow="Strategies"
        title="Strategy Controls"
        description="Configure status and parameters while preserving existing execution behavior."
      />

      <div className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
        <div className="flex flex-col gap-4 rounded-[1.25rem] bg-[var(--panel-soft)] px-4 py-4 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="ui-label">
              Paper Trading
            </p>
            <p className="mt-2 text-sm leading-6 text-[var(--text)]">
              {demoModeEnabled
                ? paperTradingEnabled
                  ? "Enabled (demo-only)"
                  : "Disabled (safe default)"
                : "Controlled by backend environment"}
            </p>
          </div>
          {demoModeEnabled ? (
            <button
              type="button"
              onClick={handlePaperToggle}
              className={`ui-button ${
                paperTradingEnabled ? "ui-button-danger" : "ui-button-primary"
              } w-full md:w-auto`}
            >
              {paperTradingEnabled ? "Disable Paper Trading" : "Enable Paper Trading"}
            </button>
          ) : (
            <span className="text-sm leading-6 text-[var(--muted)]">
              Set `PAPER_TRADING` and `WORKER_ENABLE_TRADING` on the backend.
            </span>
          )}
        </div>

        {message ? <p className="mt-4 text-sm text-[var(--muted)]">{message}</p> : null}
      </div>

      {loading ? (
        <StatePanel
          title="Loading strategies"
          description="Fetching persisted strategy settings and paper-trading status."
        />
      ) : strategies.length === 0 ? (
        <StatePanel
          title="No strategy configuration yet"
          description="Persisted strategy configuration is not available yet, so there is nothing to edit from the UI."
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {strategies.map((strategy) => (
            <StrategyCard
              key={strategy.name}
              strategy={strategy}
              onSave={handleSaveStrategy}
            />
          ))}
        </div>
      )}
    </section>
  );
}
