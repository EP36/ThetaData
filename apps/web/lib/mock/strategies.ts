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
  },
  {
    name: "breakout_momentum",
    description: "Breakout entries with volume confirmation and protective exits.",
    status: "enabled",
    parameters: {
      lookback_period: 20,
      breakout_threshold: 1.01,
      volume_multiplier: 1.5,
      stop_loss_pct: 0.02,
      take_profit_pct: 0.05,
      trailing_stop_pct: 0.02
    }
  },
  {
    name: "vwap_mean_reversion",
    description: "VWAP pullback entries with RSI confirmation and VWAP target exits.",
    status: "enabled",
    parameters: {
      vwap_window: 20,
      vwap_deviation: 0.02,
      rsi_lookback: 14,
      rsi_oversold: 30,
      rsi_overbought: 70,
      stop_loss_pct: 0.015,
      target: "vwap"
    }
  }
];
