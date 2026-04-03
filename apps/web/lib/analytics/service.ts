import {
  getContextAnalytics,
  getPortfolioAnalytics,
  getSelectionStatus,
  getStrategyAnalytics
} from "@/lib/api/client";
import type {
  ContextAnalyticsData,
  PortfolioAnalyticsData,
  SelectionStatusData,
  StrategyAnalyticsData
} from "@/lib/types";

export type AnalyticsData = {
  strategies: StrategyAnalyticsData;
  portfolio: PortfolioAnalyticsData;
  context: ContextAnalyticsData;
  selection: SelectionStatusData;
};

export async function getAnalyticsData(): Promise<AnalyticsData> {
  const [strategies, portfolio, context, selection] = await Promise.all([
    getStrategyAnalytics(),
    getPortfolioAnalytics(),
    getContextAnalytics(),
    getSelectionStatus()
  ]);

  return {
    strategies,
    portfolio,
    context,
    selection
  };
}
