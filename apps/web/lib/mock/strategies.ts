import type { StrategyConfig } from "@/lib/types";

export const mockStrategyConfigs: StrategyConfig[] = [
  {
    name: "moving_average_crossover",
    description: "Trend-following crossover with configurable MA windows.",
    status: "enabled",
    parameters: {
      short_window: 20,
      long_window: 50
    }
  },
  {
    name: "rsi_mean_reversion",
    description: "Long-only RSI pullback entries with bounded thresholds.",
    status: "enabled",
    parameters: {
      lookback: 14,
      oversold: 30,
      overbought: 70
    }
  }
];
