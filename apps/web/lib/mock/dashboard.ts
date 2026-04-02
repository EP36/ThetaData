import type { DashboardSummary, TimeSeriesPoint, TradeRow } from "@/lib/types";

export const dashboardSummary: DashboardSummary = {
  equity: 102_480.12,
  dailyPnl: 328.44,
  totalPnl: 2_480.12,
  openPositions: 2,
  systemStatus: "paper_only_ready",
  riskAlerts: ["max_daily_loss_buffer_78pct"]
};

export const equityCurve: TimeSeriesPoint[] = [
  { timestamp: "2026-03-24", value: 100_000 },
  { timestamp: "2026-03-25", value: 100_355 },
  { timestamp: "2026-03-26", value: 99_940 },
  { timestamp: "2026-03-27", value: 100_710 },
  { timestamp: "2026-03-28", value: 101_280 },
  { timestamp: "2026-03-29", value: 101_460 },
  { timestamp: "2026-03-30", value: 101_880 },
  { timestamp: "2026-03-31", value: 102_151 },
  { timestamp: "2026-04-01", value: 102_480 }
];

export const drawdownCurve: TimeSeriesPoint[] = [
  { timestamp: "2026-03-24", value: 0 },
  { timestamp: "2026-03-25", value: 0 },
  { timestamp: "2026-03-26", value: -0.0041 },
  { timestamp: "2026-03-27", value: 0 },
  { timestamp: "2026-03-28", value: 0 },
  { timestamp: "2026-03-29", value: 0 },
  { timestamp: "2026-03-30", value: 0 },
  { timestamp: "2026-03-31", value: 0 },
  { timestamp: "2026-04-01", value: 0 }
];

export const recentTrades: TradeRow[] = [
  {
    timestamp: "2026-04-01T10:00:00Z",
    symbol: "SPY",
    side: "BUY",
    quantity: 125,
    entryPrice: 510.21,
    exitPrice: 510.21,
    realizedPnl: 0,
    strategy: "moving_average_crossover",
    status: "filled"
  },
  {
    timestamp: "2026-04-01T13:45:00Z",
    symbol: "SPY",
    side: "SELL",
    quantity: 125,
    entryPrice: 510.21,
    exitPrice: 512.02,
    realizedPnl: 226.25,
    strategy: "moving_average_crossover",
    status: "filled"
  },
  {
    timestamp: "2026-04-01T14:05:00Z",
    symbol: "QQQ",
    side: "BUY",
    quantity: 40,
    entryPrice: 449.85,
    exitPrice: 449.85,
    realizedPnl: 0,
    strategy: "rsi_mean_reversion",
    status: "filled"
  }
];
