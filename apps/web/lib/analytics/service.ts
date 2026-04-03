import {
  getContextAnalytics,
  getPortfolioAnalytics,
  getWorkerExecutionStatus,
  getSelectionStatus,
  getStrategyAnalytics
} from "@/lib/api/client";
import type {
  ContextAnalyticsData,
  PortfolioAnalyticsData,
  SelectionStatusData,
  StrategyAnalyticsData,
  WorkerExecutionStatusData
} from "@/lib/types";

export type AnalyticsData = {
  strategies: StrategyAnalyticsData;
  portfolio: PortfolioAnalyticsData;
  context: ContextAnalyticsData;
  selection: SelectionStatusData;
  execution: WorkerExecutionStatusData;
};

export async function getAnalyticsData(): Promise<AnalyticsData> {
  const [strategies, portfolio, context, selection, execution] = await Promise.all([
    getStrategyAnalytics(),
    getPortfolioAnalytics(),
    getContextAnalytics(),
    getSelectionStatus(),
    getWorkerExecutionStatus()
  ]);

  return {
    strategies,
    portfolio,
    context,
    selection,
    execution
  };
}
