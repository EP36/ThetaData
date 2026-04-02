export type TimeSeriesPoint = {
  timestamp: string;
  value: number;
};

export type DashboardSummary = {
  equity: number;
  dailyPnl: number;
  totalPnl: number;
  openPositions: number;
  systemStatus: string;
  riskAlerts: string[];
};

export type TradeRow = {
  timestamp: string;
  symbol: string;
  side: "BUY" | "SELL";
  quantity: number;
  entryPrice: number;
  exitPrice: number;
  realizedPnl: number;
  strategy: string;
  status: string;
};

export type BacktestFormInput = {
  symbol: string;
  timeframe: string;
  startDate: string;
  endDate: string;
  strategy: "moving_average_crossover" | "rsi_mean_reversion";
};

export type BacktestMetrics = {
  totalReturn: number;
  sharpe: number;
  maxDrawdown: number;
  winRate: number;
  profitFactor: number;
};

export type BacktestResultData = {
  request: BacktestFormInput;
  metrics: BacktestMetrics;
  equityCurve: TimeSeriesPoint[];
  drawdownCurve: TimeSeriesPoint[];
  trades: TradeRow[];
};

export type StrategyStatus = "enabled" | "disabled";

export type StrategyConfig = {
  name: "moving_average_crossover" | "rsi_mean_reversion";
  description: string;
  status: StrategyStatus;
  parameters: Record<string, number>;
};

export type StrategyValidationErrors = Record<string, string>;

export type StrategyUpdateResult = {
  strategy: StrategyConfig | null;
  errors: StrategyValidationErrors;
};

export type RiskStatusData = {
  maxDailyLoss: number;
  currentDrawdown: number;
  maxPositionSize: number;
  grossExposure: number;
  killSwitchEnabled: boolean;
  rejectedOrders: string[];
};

export type RiskEvent = {
  timestamp: string;
  reason: string;
  severity: "info" | "warning" | "critical";
};

export type TradesFilter = {
  symbol: string;
  strategy: string;
  startDate: string;
  endDate: string;
};
