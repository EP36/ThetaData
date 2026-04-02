import { getDashboardSummary as getDashboardSummaryFromApi, getTrades } from "@/lib/api/client";
import {
  dashboardSummary as dashboardSummaryMock,
  drawdownCurve,
  equityCurve,
  recentTrades
} from "@/lib/mock/dashboard";
import type { DashboardSummary, TimeSeriesPoint, TradeRow } from "@/lib/types";

export type DashboardData = {
  summary: DashboardSummary;
  equityCurve: TimeSeriesPoint[];
  drawdownCurve: TimeSeriesPoint[];
  recentTrades: TradeRow[];
};

export async function getDashboardData(): Promise<DashboardData> {
  try {
    const [summary, trades] = await Promise.all([
      getDashboardSummaryFromApi(),
      getTrades()
    ]);
    return {
      summary,
      equityCurve,
      drawdownCurve,
      recentTrades: trades.length > 0 ? trades.slice(0, 8) : recentTrades
    };
  } catch {
    return {
      summary: dashboardSummaryMock,
      equityCurve,
      drawdownCurve,
      recentTrades
    };
  }
}
