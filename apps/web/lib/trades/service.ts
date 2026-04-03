import { mockTrades } from "@/lib/mock/trades";
import { getTrades as getTradesFromApi } from "@/lib/api/client";
import { isDemoModeEnabled } from "@/lib/runtime/demo-mode";
import type { TradeRow, TradesFilter } from "@/lib/types";

export async function getTrades(filters: TradesFilter): Promise<TradeRow[]> {
  let sourceTrades: TradeRow[];
  try {
    sourceTrades = await getTradesFromApi();
  } catch {
    sourceTrades = isDemoModeEnabled() ? mockTrades : [];
  }

  const symbol = filters.symbol.trim().toUpperCase();
  const strategy = filters.strategy.trim();
  const start = filters.startDate
    ? new Date(filters.startDate).getTime()
    : Number.NEGATIVE_INFINITY;
  const end = filters.endDate ? new Date(filters.endDate).getTime() : Number.POSITIVE_INFINITY;

  return sourceTrades.filter((trade) => {
    const tradeTimestamp = new Date(trade.timestamp).getTime();
    if (symbol && trade.symbol !== symbol) {
      return false;
    }
    if (strategy && trade.strategy !== strategy) {
      return false;
    }
    if (tradeTimestamp < start || tradeTimestamp > end) {
      return false;
    }
    return true;
  });
}
