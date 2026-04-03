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

export type AnalyticsCategory = {
  strategies: StrategyAnalyticsData;
  portfolio: PortfolioAnalyticsData;
  context: ContextAnalyticsData;
};

export type AnalyticsData = {
  backtest: AnalyticsCategory;
  paper: AnalyticsCategory;
  execution: WorkerExecutionStatusData;
  selection: SelectionStatusData;
};

export async function getAnalyticsData(): Promise<AnalyticsData> {
  const [
    backtestStrategies,
    backtestPortfolio,
    backtestContext,
    paperStrategies,
    paperPortfolio,
    paperContext,
    selection,
    execution
  ] = await Promise.all([
    getStrategyAnalytics("backtest"),
    getPortfolioAnalytics("backtest"),
    getContextAnalytics("backtest"),
    getStrategyAnalytics("paper"),
    getPortfolioAnalytics("paper"),
    getContextAnalytics("paper"),
    getSelectionStatus(),
    getWorkerExecutionStatus()
  ]);

  return {
    backtest: {
      strategies: backtestStrategies,
      portfolio: backtestPortfolio,
      context: backtestContext
    },
    paper: {
      strategies: paperStrategies,
      portfolio: paperPortfolio,
      context: paperContext
    },
    selection,
    execution
  };
}
