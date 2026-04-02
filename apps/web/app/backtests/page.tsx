"use client";

import { useMemo, useState } from "react";

import { BacktestForm } from "@/components/backtests/backtest-form";
import { BacktestResults } from "@/components/backtests/backtest-results";
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
    try {
      const nextResult = await runBacktest(form);
      setResult(nextResult);
    } catch {
      setError("Backtest failed. Please retry.");
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <section className="space-y-4">
      <div className="glass-panel rounded-3xl p-4 md:px-5 md:py-5">
        <h2 className="page-title font-semibold">Backtests</h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Run parameterized strategy simulations and review outcome quality quickly.
        </p>
      </div>

      <BacktestForm value={form} onChange={setForm} onRun={handleRun} isRunning={isRunning} />

      {error ? (
        <div className="glass-panel rounded-2xl border border-[var(--danger)] p-4 text-sm text-[var(--danger)]">
          {error}
        </div>
      ) : null}

      {isRunning ? (
        <div className="glass-panel rounded-2xl p-5 text-sm text-[var(--muted)]">
          Running backtest simulation...
        </div>
      ) : null}

      {!isRunning && result === null ? (
        <div className="glass-panel rounded-2xl p-5 text-sm text-[var(--muted)]">
          No run yet. Configure inputs and run a backtest.
        </div>
      ) : null}

      {result !== null && !isRunning ? <BacktestResults result={result} /> : null}
    </section>
  );
}
