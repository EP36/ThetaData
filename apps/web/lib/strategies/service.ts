import { mockStrategyConfigs } from "@/lib/mock/strategies";
import {
  getStrategies as getStrategiesFromApi,
  updateStrategyConfig
} from "@/lib/api/client";
import type {
  StrategyConfig,
  StrategyUpdateResult,
  StrategyValidationErrors
} from "@/lib/types";

let strategyStore: StrategyConfig[] = structuredClone(mockStrategyConfigs);
let paperTradingEnabled = false;

function findStrategy(name: StrategyConfig["name"]): StrategyConfig | undefined {
  return strategyStore.find((strategy) => strategy.name === name);
}

function validateParameters(strategy: StrategyConfig): StrategyValidationErrors {
  const errors: StrategyValidationErrors = {};
  const params = strategy.parameters;

  for (const [key, value] of Object.entries(params)) {
    if (!Number.isFinite(value)) {
      errors[key] = "Must be numeric";
    }
  }

  if (strategy.name === "moving_average_crossover") {
    if (params.short_window <= 0) {
      errors.short_window = "Must be > 0";
    }
    if (params.long_window <= 0) {
      errors.long_window = "Must be > 0";
    }
    if (params.short_window >= params.long_window) {
      errors.short_window = "Must be < long_window";
    }
  }

  if (strategy.name === "rsi_mean_reversion") {
    if (params.lookback <= 1) {
      errors.lookback = "Must be > 1";
    }
    if (params.oversold <= 0 || params.oversold >= 100) {
      errors.oversold = "Must be between 0 and 100";
    }
    if (params.overbought <= 0 || params.overbought >= 100) {
      errors.overbought = "Must be between 0 and 100";
    }
    if (params.oversold >= params.overbought) {
      errors.oversold = "Must be < overbought";
    }
  }

  return errors;
}

export async function getStrategies(): Promise<StrategyConfig[]> {
  try {
    const fromApi = await getStrategiesFromApi();
    strategyStore = structuredClone(fromApi);
    return fromApi;
  } catch {
    await new Promise((resolve) => {
      setTimeout(resolve, 200);
    });
    return structuredClone(strategyStore);
  }
}

export async function updateStrategy(
  name: StrategyConfig["name"],
  updates: Partial<Pick<StrategyConfig, "status" | "parameters">>
): Promise<StrategyUpdateResult> {
  const existing = findStrategy(name);
  if (!existing) {
    return { strategy: null, errors: { root: "Strategy not found" } };
  }

  const next: StrategyConfig = {
    ...existing,
    status: updates.status ?? existing.status,
    parameters: updates.parameters
      ? { ...existing.parameters, ...updates.parameters }
      : { ...existing.parameters }
  };

  const errors = validateParameters(next);
  if (Object.keys(errors).length > 0) {
    return { strategy: null, errors };
  }

  try {
    const updated = await updateStrategyConfig(name, updates);
    strategyStore = strategyStore.map((strategy) =>
      strategy.name === name ? updated : strategy
    );
    return { strategy: structuredClone(updated), errors: {} };
  } catch {
    await new Promise((resolve) => {
      setTimeout(resolve, 150);
    });
    strategyStore = strategyStore.map((strategy) =>
      strategy.name === name ? next : strategy
    );
    return { strategy: structuredClone(next), errors: {} };
  }
}

export async function getPaperTradingEnabled(): Promise<boolean> {
  await new Promise((resolve) => {
    setTimeout(resolve, 100);
  });
  return paperTradingEnabled;
}

export async function setPaperTradingEnabled(enabled: boolean): Promise<boolean> {
  await new Promise((resolve) => {
    setTimeout(resolve, 120);
  });
  paperTradingEnabled = enabled;
  return paperTradingEnabled;
}

export function resetStrategyMockState(): void {
  strategyStore = structuredClone(mockStrategyConfigs);
  paperTradingEnabled = false;
}
