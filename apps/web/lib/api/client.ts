import type {
  BacktestFormInput,
  BacktestResultData,
  ContextAnalyticsData,
  DashboardSummary,
  PortfolioAnalyticsData,
  RiskStatusData,
  SelectionStatusData,
  StrategyAnalyticsData,
  StrategyConfig,
  TradeRow
} from "@/lib/types";

type ApiPoint = {
  timestamp: string;
  value: number;
};

type ApiTrade = {
  timestamp: string;
  symbol: string;
  side: "BUY" | "SELL";
  quantity: number;
  entry_price: number;
  exit_price: number;
  realized_pnl: number;
  strategy: string;
  status: string;
};

type ApiBacktestResponse = {
  run_id: string;
  symbol: string;
  timeframe: string;
  strategy: BacktestFormInput["strategy"];
  metrics: Record<string, number>;
  equity_curve: ApiPoint[];
  drawdown_curve: ApiPoint[];
  trades: ApiTrade[];
};

type ApiDashboardSummary = {
  equity: number;
  daily_pnl: number;
  total_pnl: number;
  open_positions: number;
  system_status: string;
  risk_alerts: string[];
  last_run_id: string | null;
};

type ApiRiskStatus = {
  kill_switch_enabled: boolean;
  current_drawdown: number;
  gross_exposure: number;
  max_daily_loss: number;
  max_position_size: number;
  max_open_positions: number;
  max_gross_exposure: number;
  rejected_orders: string[];
};

type ApiTradesResponse = {
  trades: ApiTrade[];
  total: number;
};

type ApiKillSwitchResponse = {
  kill_switch_enabled: boolean;
  updated_at: string;
};

type ApiRollingMetricPoint = {
  trade_index: number;
  timestamp: string;
  win_rate: number;
  expectancy: number;
  sharpe: number;
};

type ApiRecentWindowMetrics = {
  trades: number;
  total_return: number;
  win_rate: number;
  expectancy: number;
  sharpe: number;
};

type ApiStrategyAnalyticsRecord = {
  strategy: string;
  total_return: number;
  win_rate: number;
  average_win: number;
  average_loss: number;
  profit_factor: number;
  expectancy: number;
  sharpe: number;
  max_drawdown: number;
  num_trades: number;
  average_hold_time_hours: number;
  rolling_20_win_rate: number;
  rolling_20_expectancy: number;
  rolling_20_sharpe: number;
  rolling_20_series: ApiRollingMetricPoint[];
  last_5: ApiRecentWindowMetrics;
  last_20: ApiRecentWindowMetrics;
  last_60: ApiRecentWindowMetrics;
};

type ApiStrategyAnalyticsResponse = {
  generated_at: string;
  strategies: ApiStrategyAnalyticsRecord[];
};

type ApiStrategyContribution = {
  strategy: string;
  realized_pnl: number;
  return_pct: number;
  trades: number;
};

type ApiSymbolExposure = {
  symbol: string;
  quantity: number;
  avg_price: number;
  notional: number;
  unrealized_pnl: number;
};

type ApiOpenRiskSummary = {
  open_positions: number;
  gross_exposure: number;
  largest_position_notional: number;
  cash: number;
  day_start_equity: number;
  peak_equity: number;
};

type ApiPortfolioAnalyticsResponse = {
  generated_at: string;
  equity_curve: ApiPoint[];
  daily_pnl: ApiPoint[];
  realized_pnl: number;
  unrealized_pnl: number;
  rolling_drawdown: ApiPoint[];
  strategy_contribution: ApiStrategyContribution[];
  exposure_by_symbol: ApiSymbolExposure[];
  open_risk_summary: ApiOpenRiskSummary;
};

type ApiContextBucketPerformance = {
  key: string;
  trades: number;
  total_return: number;
  win_rate: number;
  expectancy: number;
  sharpe: number;
  total_pnl: number;
};

type ApiContextAnalyticsResponse = {
  generated_at: string;
  by_symbol: ApiContextBucketPerformance[];
  by_timeframe: ApiContextBucketPerformance[];
  by_weekday: ApiContextBucketPerformance[];
  by_hour: ApiContextBucketPerformance[];
  by_regime: ApiContextBucketPerformance[];
};

type ApiStrategyScore = {
  strategy: string;
  signal: number;
  eligible: boolean;
  reasons: string[];
  score: number;
  recent_expectancy: number;
  recent_sharpe: number;
  win_rate: number;
  drawdown_penalty: number;
  regime_fit: number;
  sizing_multiplier: number;
};

type ApiSelectionStatusResponse = {
  generated_at: string;
  regime: string;
  regime_signals: Record<string, number>;
  selected_strategy: string | null;
  selected_score: number;
  minimum_score_threshold: number;
  sizing_multiplier: number;
  allocation_fraction: number;
  candidates: ApiStrategyScore[];
};

function apiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    cache: "no-store"
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`API ${response.status}: ${body}`);
  }
  return (await response.json()) as T;
}

function mapTradeRow(trade: ApiTrade): TradeRow {
  return {
    timestamp: trade.timestamp,
    symbol: trade.symbol,
    side: trade.side,
    quantity: trade.quantity,
    entryPrice: trade.entry_price,
    exitPrice: trade.exit_price,
    realizedPnl: trade.realized_pnl,
    strategy: trade.strategy,
    status: trade.status
  };
}

export async function getDashboardSummary(): Promise<DashboardSummary> {
  const payload = await fetchJson<ApiDashboardSummary>("/api/dashboard/summary");
  return {
    equity: payload.equity,
    dailyPnl: payload.daily_pnl,
    totalPnl: payload.total_pnl,
    openPositions: payload.open_positions,
    systemStatus: payload.system_status,
    riskAlerts: payload.risk_alerts
  };
}

export async function getBacktestResults(
  request: BacktestFormInput
): Promise<BacktestResultData> {
  const payload = await fetchJson<ApiBacktestResponse>("/api/backtests/run", {
    method: "POST",
    body: JSON.stringify({
      symbol: request.symbol,
      timeframe: request.timeframe,
      start: request.startDate || null,
      end: request.endDate || null,
      strategy: request.strategy
    })
  });

  return {
    request,
    metrics: {
      totalReturn: payload.metrics.total_return ?? 0,
      sharpe: payload.metrics.sharpe ?? 0,
      maxDrawdown: payload.metrics.max_drawdown ?? 0,
      winRate: payload.metrics.win_rate ?? 0,
      profitFactor: payload.metrics.profit_factor ?? 0,
      riskPerTrade: payload.metrics.risk_per_trade ?? 0,
      riskPerTradePct: payload.metrics.risk_per_trade_pct ?? 0.01,
      positionSizePct: payload.metrics.position_size_pct ?? 0
    },
    equityCurve: payload.equity_curve,
    drawdownCurve: payload.drawdown_curve,
    trades: payload.trades.map(mapTradeRow)
  };
}

export async function getStrategies(): Promise<StrategyConfig[]> {
  const payload = await fetchJson<Array<Omit<StrategyConfig, "parameters"> & { parameters: Record<string, number | string> }>>(
    "/api/strategies"
  );
  return payload.map((strategy) => ({
    ...strategy,
    parameters: strategy.parameters
  }));
}

export async function updateStrategyConfig(
  name: StrategyConfig["name"],
  updates: Partial<Pick<StrategyConfig, "status" | "parameters">>
): Promise<StrategyConfig> {
  return fetchJson<StrategyConfig>(`/api/strategies/${name}`, {
    method: "PATCH",
    body: JSON.stringify({
      status: updates.status,
      parameters: updates.parameters
    })
  });
}

export async function getRiskStatus(): Promise<RiskStatusData> {
  const payload = await fetchJson<ApiRiskStatus>("/api/risk/status");
  return {
    maxDailyLoss: payload.max_daily_loss,
    currentDrawdown: payload.current_drawdown,
    maxPositionSize: payload.max_position_size,
    grossExposure: payload.gross_exposure,
    killSwitchEnabled: payload.kill_switch_enabled,
    rejectedOrders: payload.rejected_orders
  };
}

export async function getTrades(): Promise<TradeRow[]> {
  const payload = await fetchJson<ApiTradesResponse>("/api/trades");
  return payload.trades.map(mapTradeRow);
}

export async function triggerKillSwitch(enabled = true): Promise<boolean> {
  const payload = await fetchJson<ApiKillSwitchResponse>("/api/system/kill-switch", {
    method: "POST",
    body: JSON.stringify({ enabled })
  });
  return payload.kill_switch_enabled;
}

export async function getStrategyAnalytics(): Promise<StrategyAnalyticsData> {
  const payload = await fetchJson<ApiStrategyAnalyticsResponse>("/api/analytics/strategies");
  return {
    generatedAt: payload.generated_at,
    strategies: payload.strategies.map((item) => ({
      strategy: item.strategy,
      totalReturn: item.total_return,
      winRate: item.win_rate,
      averageWin: item.average_win,
      averageLoss: item.average_loss,
      profitFactor: item.profit_factor,
      expectancy: item.expectancy,
      sharpe: item.sharpe,
      maxDrawdown: item.max_drawdown,
      numTrades: item.num_trades,
      averageHoldTimeHours: item.average_hold_time_hours,
      rolling20WinRate: item.rolling_20_win_rate,
      rolling20Expectancy: item.rolling_20_expectancy,
      rolling20Sharpe: item.rolling_20_sharpe,
      rolling20Series: item.rolling_20_series.map((point) => ({
        tradeIndex: point.trade_index,
        timestamp: point.timestamp,
        winRate: point.win_rate,
        expectancy: point.expectancy,
        sharpe: point.sharpe
      })),
      last5: {
        trades: item.last_5.trades,
        totalReturn: item.last_5.total_return,
        winRate: item.last_5.win_rate,
        expectancy: item.last_5.expectancy,
        sharpe: item.last_5.sharpe
      },
      last20: {
        trades: item.last_20.trades,
        totalReturn: item.last_20.total_return,
        winRate: item.last_20.win_rate,
        expectancy: item.last_20.expectancy,
        sharpe: item.last_20.sharpe
      },
      last60: {
        trades: item.last_60.trades,
        totalReturn: item.last_60.total_return,
        winRate: item.last_60.win_rate,
        expectancy: item.last_60.expectancy,
        sharpe: item.last_60.sharpe
      }
    }))
  };
}

export async function getPortfolioAnalytics(): Promise<PortfolioAnalyticsData> {
  const payload = await fetchJson<ApiPortfolioAnalyticsResponse>("/api/analytics/portfolio");
  return {
    generatedAt: payload.generated_at,
    equityCurve: payload.equity_curve,
    dailyPnl: payload.daily_pnl,
    realizedPnl: payload.realized_pnl,
    unrealizedPnl: payload.unrealized_pnl,
    rollingDrawdown: payload.rolling_drawdown,
    strategyContribution: payload.strategy_contribution.map((item) => ({
      strategy: item.strategy,
      realizedPnl: item.realized_pnl,
      returnPct: item.return_pct,
      trades: item.trades
    })),
    exposureBySymbol: payload.exposure_by_symbol.map((item) => ({
      symbol: item.symbol,
      quantity: item.quantity,
      avgPrice: item.avg_price,
      notional: item.notional,
      unrealizedPnl: item.unrealized_pnl
    })),
    openRiskSummary: {
      openPositions: payload.open_risk_summary.open_positions,
      grossExposure: payload.open_risk_summary.gross_exposure,
      largestPositionNotional: payload.open_risk_summary.largest_position_notional,
      cash: payload.open_risk_summary.cash,
      dayStartEquity: payload.open_risk_summary.day_start_equity,
      peakEquity: payload.open_risk_summary.peak_equity
    }
  };
}

export async function getContextAnalytics(): Promise<ContextAnalyticsData> {
  const payload = await fetchJson<ApiContextAnalyticsResponse>("/api/analytics/context");
  const mapBucket = (item: ApiContextBucketPerformance) => ({
    key: item.key,
    trades: item.trades,
    totalReturn: item.total_return,
    winRate: item.win_rate,
    expectancy: item.expectancy,
    sharpe: item.sharpe,
    totalPnl: item.total_pnl
  });
  return {
    generatedAt: payload.generated_at,
    bySymbol: payload.by_symbol.map(mapBucket),
    byTimeframe: payload.by_timeframe.map(mapBucket),
    byWeekday: payload.by_weekday.map(mapBucket),
    byHour: payload.by_hour.map(mapBucket),
    byRegime: payload.by_regime.map(mapBucket)
  };
}

export async function getSelectionStatus(): Promise<SelectionStatusData> {
  const payload = await fetchJson<ApiSelectionStatusResponse>("/api/selection/status");
  return {
    generatedAt: payload.generated_at,
    regime: payload.regime,
    regimeSignals: payload.regime_signals,
    selectedStrategy: payload.selected_strategy,
    selectedScore: payload.selected_score,
    minimumScoreThreshold: payload.minimum_score_threshold,
    sizingMultiplier: payload.sizing_multiplier,
    allocationFraction: payload.allocation_fraction,
    candidates: payload.candidates.map((item) => ({
      strategy: item.strategy,
      signal: item.signal,
      eligible: item.eligible,
      reasons: item.reasons,
      score: item.score,
      recentExpectancy: item.recent_expectancy,
      recentSharpe: item.recent_sharpe,
      winRate: item.win_rate,
      drawdownPenalty: item.drawdown_penalty,
      regimeFit: item.regime_fit,
      sizingMultiplier: item.sizing_multiplier
    }))
  };
}
