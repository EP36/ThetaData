import type { TradeRow } from "@/lib/types";

export const mockTrades: TradeRow[] = [
  {
    timestamp: "2026-03-18T14:10:00Z",
    symbol: "SPY",
    side: "BUY",
    quantity: 100,
    entryPrice: 505.2,
    exitPrice: 505.2,
    realizedPnl: 0,
    strategy: "moving_average_crossover",
    status: "filled"
  },
  {
    timestamp: "2026-03-20T15:55:00Z",
    symbol: "SPY",
    side: "SELL",
    quantity: 100,
    entryPrice: 505.2,
    exitPrice: 509.6,
    realizedPnl: 440,
    strategy: "moving_average_crossover",
    status: "filled"
  },
  {
    timestamp: "2026-03-22T13:42:00Z",
    symbol: "QQQ",
    side: "BUY",
    quantity: 45,
    entryPrice: 447.4,
    exitPrice: 447.4,
    realizedPnl: 0,
    strategy: "rsi_mean_reversion",
    status: "filled"
  },
  {
    timestamp: "2026-03-25T19:12:00Z",
    symbol: "QQQ",
    side: "SELL",
    quantity: 45,
    entryPrice: 447.4,
    exitPrice: 444.3,
    realizedPnl: -139.5,
    strategy: "rsi_mean_reversion",
    status: "filled"
  }
];
