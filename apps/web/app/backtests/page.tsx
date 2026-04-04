"use client";

import { useMemo, useState } from "react";

import { BacktestForm } from "@/components/backtests/backtest-form";
import { BacktestResults } from "@/components/backtests/backtest-results";
import { PageHeader } from "@/components/ui/page-header";
import { StatePanel } from "@/components/ui/state-panel";
import { runBacktest } from "@/lib/backtests/service";
import type { BacktestFormInput, BacktestResultData } from "@/lib/types";

const DEFAULT_FORM: BacktestFormInput = {
  symbol: "SPY",
  timeframe: "1d",
  startDate: "2025-01-01",
  endDate: "2025-12-31",
  strategy: "moving_average_crossover"
};

function formIsValid(value: BacktestFormInput): boolean {
  return Boolean(value.symbol.trim() && value.startDate && value.endDate);
}

export default function BacktestsPage() {
  const [form, setForm] = useState<BacktestFormInput>(DEFAULT_FORM);
  const [result, setResult] = useState<BacktestResultData | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canRun = useMemo(() => formIsValid(form) && !isRunning, [form, isRunning]);

  const handleRun = async () => {
    if (!canRun) {
      return;
    }
    setIsRunning(true);
    setError(null);
    setResult(null);
    try {
      const nextResult = await runBacktest(form);
      setResult(nextResult);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "";
      if (detail) {
        setError(`Backtest failed: ${detail}`);
      } else {
        setError("Backtest failed. Please retry.");
      }
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <section className="space-y-4">
      <PageHeader
        eyebrow="Backtests"
        title="Simulation Workspace"
        description="Run parameterized strategy simulations and review outcome quality quickly."
      />

      <BacktestForm value={form} onChange={setForm} onRun={handleRun} isRunning={isRunning} />

      {error ? (
        <StatePanel title="Backtest failed" description={error} tone="danger" />
      ) : null}

      {isRunning ? (
        <StatePanel
          title="Running backtest"
          description="The simulation is processing market data, signals, and portfolio accounting."
        />
      ) : null}

      {!isRunning && result === null && !error ? (
        <StatePanel
          title="Ready to simulate"
          description="Configure the inputs above and run a backtest to view metrics, charts, and trades."
        />
      ) : null}

      {result !== null && !isRunning ? <BacktestResults result={result} /> : null}
    </section>
  );
}
