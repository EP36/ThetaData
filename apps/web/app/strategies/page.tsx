"use client";

import { useEffect, useState } from "react";

import { StrategyCard } from "@/components/strategies/strategy-card";
import {
  getPaperTradingEnabled,
  getStrategies,
  setPaperTradingEnabled,
  updateStrategy
} from "@/lib/strategies/service";
import type { StrategyConfig, StrategyValidationErrors } from "@/lib/types";

export default function StrategiesPage() {
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
    <section className="space-y-4">
      <div className="glass-panel rounded-3xl p-4 md:px-5 md:py-5">
        <h2 className="page-title font-semibold">Strategies</h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Configure strategy status and parameters with inline validation.
        </p>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-[var(--panel-soft)] px-4 py-3">
          <div>
            <p className="text-xs uppercase tracking-[0.12em] text-[var(--muted)]">
              Paper Trading
            </p>
            <p className="text-sm">
              {paperTradingEnabled ? "Enabled (mock)" : "Disabled (safe default)"}
            </p>
          </div>
          <button
            type="button"
            onClick={handlePaperToggle}
            className={`ui-button ${
              paperTradingEnabled ? "ui-button-danger" : "ui-button-primary"
            }`}
          >
            {paperTradingEnabled ? "Disable Paper Trading" : "Enable Paper Trading"}
          </button>
        </div>

        {message ? <p className="mt-3 text-sm text-[var(--muted)]">{message}</p> : null}
      </div>

      {loading ? (
        <div className="glass-panel rounded-2xl p-5 text-sm text-[var(--muted)]">
          Loading strategies...
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
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
