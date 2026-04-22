import { getDashboardSummary as getDashboardSummaryFromApi, getTrades } from "@/lib/api/client";
import {
  dashboardSummary as dashboardSummaryMock,
  drawdownCurve,
  equityCurve,
  recentTrades
} from "@/lib/mock/dashboard";
import { isDemoModeEnabled } from "@/lib/runtime/demo-mode";
import type { DashboardSummary, TimeSeriesPoint, TradeRow } from "@/lib/types";

export type DashboardData = {
  summary: DashboardSummary;
  equityCurve: TimeSeriesPoint[];
  drawdownCurve: TimeSeriesPoint[];
  recentTrades: TradeRow[];
};

const EMPTY_DASHBOARD_SUMMARY: DashboardSummary = {
  equity: null,
  dailyPnl: 0,
  totalPnl: 0,
  openPositions: 0,
  systemStatus: "trading_disabled",
  riskAlerts: [],
  tradingStatus: {
    signalProvider: "synthetic",
    tradingVenue: "alpaca",
    tradingMode: "disabled",
    polyTradingMode: "disabled",
    alpacaTradingMode: "disabled",
    polyDryRun: true,
    workerEnableTrading: false,
    workerDryRun: true,
    paperTradingEnabled: false,
    liveTradingEnabled: false,
    executionAdapter: "alpaca_execution_disabled"
  }
};

const BACKEND_UNAVAILABLE_SUMMARY: DashboardSummary = {
  ...EMPTY_DASHBOARD_SUMMARY,
  systemStatus: "backend_unavailable",
  riskAlerts: ["backend_unavailable"]
};

export async function getDashboardData(): Promise<DashboardData> {
  const demoModeEnabled = isDemoModeEnabled();

  if (demoModeEnabled) {
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

  try {
    const [summary, trades] = await Promise.all([
      getDashboardSummaryFromApi(),
      getTrades()
    ]);
    return {
      summary,
      equityCurve: [],
      drawdownCurve: [],
      recentTrades: trades.slice(0, 8)
    };
  } catch {
    return {
      summary: BACKEND_UNAVAILABLE_SUMMARY,
      equityCurve: [],
      drawdownCurve: [],
      recentTrades: []
    };
  }
}
