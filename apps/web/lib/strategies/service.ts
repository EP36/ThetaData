import { mockStrategyConfigs } from "@/lib/mock/strategies";
import { isDemoModeEnabled } from "@/lib/runtime/demo-mode";
import {
  getStrategies as getStrategiesFromApi,
  updateStrategyConfig
} from "@/lib/api/client";
import type {
  StrategyConfig,
  StrategyUpdateResult,
  StrategyValidationErrors
} from "@/lib/types";

let strategyStore: StrategyConfig[] = [];
let paperTradingEnabled = false;

function findStrategy(name: StrategyConfig["name"]): StrategyConfig | undefined {
  return strategyStore.find((strategy) => strategy.name === name);
}

function validateParameters(strategy: StrategyConfig): StrategyValidationErrors {
  const errors: StrategyValidationErrors = {};
  const params = strategy.parameters;

  for (const [key, value] of Object.entries(params)) {
    if (typeof value === "number" && !Number.isFinite(value)) {
      errors[key] = "Must be numeric";
    }
  }

  if (strategy.name === "moving_average_crossover") {
    if (Number(params.short_window) <= 0) {
      errors.short_window = "Must be > 0";
    }
    if (Number(params.long_window) <= 0) {
      errors.long_window = "Must be > 0";
    }
    if (Number(params.short_window) >= Number(params.long_window)) {
      errors.short_window = "Must be < long_window";
    }
  }

  if (strategy.name === "rsi_mean_reversion") {
    if (Number(params.lookback) <= 1) {
      errors.lookback = "Must be > 1";
    }
    if (Number(params.oversold) <= 0 || Number(params.oversold) >= 100) {
      errors.oversold = "Must be between 0 and 100";
    }
    if (Number(params.overbought) <= 0 || Number(params.overbought) >= 100) {
      errors.overbought = "Must be between 0 and 100";
    }
    if (Number(params.oversold) >= Number(params.overbought)) {
      errors.oversold = "Must be < overbought";
    }
  }

  if (strategy.name === "breakout_momentum") {
    if (Number(params.lookback_period) <= 1) {
      errors.lookback_period = "Must be > 1";
    }
    if (Number(params.breakout_threshold) <= 1.0) {
      errors.breakout_threshold = "Must be > 1.0";
    }
    if (Number(params.volume_multiplier) <= 0) {
      errors.volume_multiplier = "Must be > 0";
    }
    if (Number(params.stop_loss_pct) <= 0 || Number(params.stop_loss_pct) >= 1) {
      errors.stop_loss_pct = "Must be between 0 and 1";
    }
    if (Number(params.take_profit_pct) <= 0) {
      errors.take_profit_pct = "Must be > 0";
    }
    if (Number(params.trailing_stop_pct) <= 0 || Number(params.trailing_stop_pct) >= 1) {
      errors.trailing_stop_pct = "Must be between 0 and 1";
    }
  }

  if (strategy.name === "vwap_mean_reversion") {
    if (Number(params.vwap_window) <= 1) {
      errors.vwap_window = "Must be > 1";
    }
    if (Number(params.vwap_deviation) <= 0 || Number(params.vwap_deviation) >= 1) {
      errors.vwap_deviation = "Must be between 0 and 1";
    }
    if (Number(params.rsi_lookback) <= 1) {
      errors.rsi_lookback = "Must be > 1";
    }
    if (Number(params.rsi_oversold) <= 0 || Number(params.rsi_oversold) >= 100) {
      errors.rsi_oversold = "Must be between 0 and 100";
    }
    if (Number(params.rsi_overbought) <= 0 || Number(params.rsi_overbought) >= 100) {
      errors.rsi_overbought = "Must be between 0 and 100";
    }
    if (Number(params.rsi_oversold) >= Number(params.rsi_overbought)) {
      errors.rsi_oversold = "Must be < rsi_overbought";
    }
    if (String(params.target).trim().toLowerCase() !== "vwap") {
      errors.target = "Target must be 'vwap'";
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
    if (isDemoModeEnabled()) {
      if (strategyStore.length === 0) {
        strategyStore = structuredClone(mockStrategyConfigs);
      }
    }
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
    if (!isDemoModeEnabled()) {
      return { strategy: null, errors: { root: "Unable to update strategy settings." } };
    }
    strategyStore = strategyStore.map((strategy) =>
      strategy.name === name ? next : strategy
    );
    return { strategy: structuredClone(next), errors: {} };
  }
}

export async function getPaperTradingEnabled(): Promise<boolean> {
  if (!isDemoModeEnabled()) {
    return false;
  }
  return paperTradingEnabled;
}

export async function setPaperTradingEnabled(enabled: boolean): Promise<boolean> {
  if (!isDemoModeEnabled()) {
    return false;
  }
  paperTradingEnabled = enabled;
  return paperTradingEnabled;
}

export function resetStrategyMockState(): void {
  strategyStore = [];
  if (isDemoModeEnabled()) {
    strategyStore = structuredClone(mockStrategyConfigs);
  }
  paperTradingEnabled = false;
}
