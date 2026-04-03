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
  strategy:
    | "moving_average_crossover"
    | "rsi_mean_reversion"
    | "breakout_momentum"
    | "vwap_mean_reversion";
};

export type BacktestMetrics = {
  totalReturn: number;
  sharpe: number;
  maxDrawdown: number;
  winRate: number;
  profitFactor: number;
  riskPerTrade: number;
  riskPerTradePct: number;
  positionSizePct: number;
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
  name:
    | "moving_average_crossover"
    | "rsi_mean_reversion"
    | "breakout_momentum"
    | "vwap_mean_reversion";
  description: string;
  status: StrategyStatus;
  parameters: Record<string, number | string>;
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

export type RollingMetricPoint = {
  tradeIndex: number;
  timestamp: string;
  winRate: number;
  expectancy: number;
  sharpe: number;
};

export type RecentWindowMetrics = {
  trades: number;
  totalReturn: number;
  winRate: number;
  expectancy: number;
  sharpe: number;
};

export type StrategyAnalyticsRecord = {
  strategy: string;
  totalReturn: number;
  winRate: number;
  averageWin: number;
  averageLoss: number;
  profitFactor: number;
  expectancy: number;
  sharpe: number;
  maxDrawdown: number;
  numTrades: number;
  averageHoldTimeHours: number;
  rolling20WinRate: number;
  rolling20Expectancy: number;
  rolling20Sharpe: number;
  rolling20Series: RollingMetricPoint[];
  last5: RecentWindowMetrics;
  last20: RecentWindowMetrics;
  last60: RecentWindowMetrics;
};

export type StrategyAnalyticsData = {
  generatedAt: string;
  dataSource: "execution" | "paper" | "backtest";
  strategies: StrategyAnalyticsRecord[];
};

export type StrategyContribution = {
  strategy: string;
  realizedPnl: number;
  returnPct: number;
  trades: number;
};

export type SymbolExposure = {
  symbol: string;
  quantity: number;
  avgPrice: number;
  notional: number;
  unrealizedPnl: number;
};

export type OpenRiskSummary = {
  openPositions: number;
  grossExposure: number;
  largestPositionNotional: number;
  cash: number;
  dayStartEquity: number;
  peakEquity: number;
};

export type PortfolioAnalyticsData = {
  generatedAt: string;
  dataSource: "execution" | "paper" | "backtest";
  equityCurve: TimeSeriesPoint[];
  dailyPnl: TimeSeriesPoint[];
  realizedPnl: number;
  unrealizedPnl: number;
  rollingDrawdown: TimeSeriesPoint[];
  strategyContribution: StrategyContribution[];
  exposureBySymbol: SymbolExposure[];
  openRiskSummary: OpenRiskSummary;
};

export type ContextBucketPerformance = {
  key: string;
  trades: number;
  totalReturn: number;
  winRate: number;
  expectancy: number;
  sharpe: number;
  totalPnl: number;
};

export type ContextAnalyticsData = {
  generatedAt: string;
  dataSource: "execution" | "paper" | "backtest";
  bySymbol: ContextBucketPerformance[];
  byTimeframe: ContextBucketPerformance[];
  byWeekday: ContextBucketPerformance[];
  byHour: ContextBucketPerformance[];
  byRegime: ContextBucketPerformance[];
};

export type StrategyScore = {
  strategy: string;
  signal: number;
  eligible: boolean;
  reasons: string[];
  score: number;
  recentExpectancy: number;
  recentSharpe: number;
  winRate: number;
  drawdownPenalty: number;
  regimeFit: number;
  sizingMultiplier: number;
};

export type SelectionStatusData = {
  generatedAt: string;
  regime: string;
  regimeSignals: Record<string, number>;
  selectedStrategy: string | null;
  selectedScore: number;
  minimumScoreThreshold: number;
  sizingMultiplier: number;
  allocationFraction: number;
  candidates: StrategyScore[];
};

export type WorkerSymbolDecision = {
  symbol: string;
  timeframe: string;
  runId: string | null;
  updatedAt: string | null;
  action: string;
  orderStatus: string | null;
  selectedStrategy: string | null;
  activeStrategy: string | null;
  selectedScore: number;
  noTradeReason: string | null;
  rejectionReasons: string[];
  candidates: StrategyScore[];
};

export type WorkerExecutionStatusData = {
  generatedAt: string;
  workerName: string;
  timeframe: string;
  universeMode: string;
  dryRunEnabled: boolean;
  universeSymbols: string[];
  scannedSymbols: string[];
  shortlistedSymbols: string[];
  allowMultiStrategyPerSymbol: boolean;
  selectedSymbol: string | null;
  selectedStrategy: string | null;
  lastSelectedSymbol: string | null;
  lastSelectedStrategy: string | null;
  lastNoTradeReason: string | null;
  symbolFilterReasons: Record<string, string[]>;
  activeStrategyBySymbol: Record<string, string>;
  symbols: WorkerSymbolDecision[];
};
