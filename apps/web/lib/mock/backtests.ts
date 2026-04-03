import type { BacktestFormInput, BacktestMetrics, BacktestResultData, TimeSeriesPoint, TradeRow } from "@/lib/types";

const BASE_EQUITY: TimeSeriesPoint[] = [
  { timestamp: "2026-03-01", value: 100_000 },
  { timestamp: "2026-03-05", value: 100_540 },
  { timestamp: "2026-03-10", value: 99_910 },
  { timestamp: "2026-03-15", value: 101_240 },
  { timestamp: "2026-03-20", value: 102_120 },
  { timestamp: "2026-03-25", value: 101_860 },
  { timestamp: "2026-03-30", value: 102_950 }
];

const BASE_TRADES: TradeRow[] = [
  {
    timestamp: "2026-03-05T14:00:00Z",
    symbol: "SPY",
    side: "BUY",
    quantity: 120,
    entryPrice: 504.2,
    exitPrice: 504.2,
    realizedPnl: 0,
    strategy: "moving_average_crossover",
    status: "filled"
  },
  {
    timestamp: "2026-03-11T15:30:00Z",
    symbol: "SPY",
    side: "SELL",
    quantity: 120,
    entryPrice: 504.2,
    exitPrice: 510.7,
    realizedPnl: 780,
    strategy: "moving_average_crossover",
    status: "filled"
  },
  {
    timestamp: "2026-03-24T13:10:00Z",
    symbol: "SPY",
    side: "BUY",
    quantity: 95,
    entryPrice: 508.3,
    exitPrice: 508.3,
    realizedPnl: 0,
    strategy: "moving_average_crossover",
    status: "filled"
  }
];

function computeDrawdown(equityCurve: TimeSeriesPoint[]): TimeSeriesPoint[] {
  let peak = Number.NEGATIVE_INFINITY;
  return equityCurve.map((point) => {
    peak = Math.max(peak, point.value);
    const value = peak > 0 ? point.value / peak - 1 : 0;
    return { timestamp: point.timestamp, value };
  });
}

function strategyMetrics(strategy: BacktestFormInput["strategy"]): BacktestMetrics {
  const baseRisk = {
    riskPerTrade: 1_000,
    riskPerTradePct: 0.01,
    positionSizePct: strategy === "vwap_mean_reversion" ? 0.25 : 0.25
  };

  if (strategy === "rsi_mean_reversion") {
    return {
      totalReturn: 0.0204,
      sharpe: 1.12,
      maxDrawdown: -0.013,
      winRate: 0.58,
      profitFactor: 1.44,
      ...baseRisk
    };
  }
  if (strategy === "breakout_momentum") {
    return {
      totalReturn: 0.0355,
      sharpe: 1.42,
      maxDrawdown: -0.02,
      winRate: 0.57,
      profitFactor: 1.61,
      ...baseRisk
    };
  }
  if (strategy === "vwap_mean_reversion") {
    return {
      totalReturn: 0.0181,
      sharpe: 1.05,
      maxDrawdown: -0.011,
      winRate: 0.62,
      profitFactor: 1.37,
      ...baseRisk
    };
  }
  return {
    totalReturn: 0.0295,
    sharpe: 1.34,
    maxDrawdown: -0.016,
    winRate: 0.61,
    profitFactor: 1.58,
    ...baseRisk
  };
}

export async function runMockBacktest(
  request: BacktestFormInput
): Promise<BacktestResultData> {
  await new Promise((resolve) => {
    setTimeout(resolve, 420);
  });

  const metrics = strategyMetrics(request.strategy);
  const trades = BASE_TRADES.map((trade) => ({
    ...trade,
    symbol: request.symbol.toUpperCase(),
    strategy: request.strategy
  }));

  return {
    request,
    metrics,
    equityCurve: BASE_EQUITY,
    drawdownCurve: computeDrawdown(BASE_EQUITY),
    trades
  };
}
