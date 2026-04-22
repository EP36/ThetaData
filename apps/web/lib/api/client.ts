import type {
  AuthSessionData,
  BacktestFormInput,
  BacktestResultData,
  ContextAnalyticsData,
  DashboardSummary,
  PortfolioAnalyticsData,
  RiskStatusData,
  SelectionStatusData,
  StrategyAnalyticsData,
  StrategyConfig,
  TradeRow,
  WorkerExecutionStatusData
} from "@/lib/types";
import {
  clearAuthToken,
  dispatchAuthExpired,
  getAuthToken,
  setAuthToken
} from "@/lib/auth/session";

type AnalyticsSource = "execution" | "paper" | "backtest";

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
  trading_status?: ApiTradingStatus;
};

type ApiTradingStatus = {
  signal_provider: string;
  trading_venue: string;
  trading_mode: string;
  poly_trading_mode: string;
  alpaca_trading_mode: string;
  poly_dry_run: boolean;
  worker_enable_trading: boolean;
  worker_dry_run: boolean;
  paper_trading_enabled: boolean;
  live_trading_enabled: boolean;
  execution_adapter: string;
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
  data_source: AnalyticsSource;
  aggregation_scope: "single_run" | "multi_run_aggregate";
  run_count: number;
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
  data_source: AnalyticsSource;
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
  data_source: AnalyticsSource;
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

type ApiWorkerSymbolDecision = {
  symbol: string;
  timeframe: string;
  run_id: string | null;
  updated_at: string | null;
  action: string;
  order_status: string | null;
  selected_strategy: string | null;
  active_strategy: string | null;
  selected_score: number;
  no_trade_reason: string | null;
  rejection_reasons: string[];
  candidates: ApiStrategyScore[];
};

type ApiWorkerExecutionStatusResponse = {
  generated_at: string;
  worker_name: string;
  timeframe: string;
  universe_mode: string;
  dry_run_enabled: boolean;
  universe_symbols: string[];
  scanned_symbols: string[];
  shortlisted_symbols: string[];
  allow_multi_strategy_per_symbol: boolean;
  selected_symbol: string | null;
  selected_strategy: string | null;
  last_selected_symbol: string | null;
  last_selected_strategy: string | null;
  last_no_trade_reason: string | null;
  symbol_filter_reasons: Record<string, string[]>;
  active_strategy_by_symbol: Record<string, string>;
  symbols: ApiWorkerSymbolDecision[];
};

type ApiAuthUser = {
  id: number;
  email: string;
  role: string;
  is_active: boolean;
};

type ApiAuthLoginResponse = {
  token: string;
  expires_at: string;
  user: ApiAuthUser;
};

type ApiAuthSessionResponse = {
  user: ApiAuthUser;
  expires_at: string;
};

type ApiLogoutResponse = {
  ok: boolean;
};

type ApiPasswordChangeResponse = {
  ok: boolean;
};

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function apiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const authToken = getAuthToken();
  const providedHeaders = new Headers(init?.headers);
  if (!providedHeaders.has("Content-Type")) {
    providedHeaders.set("Content-Type", "application/json");
  }
  if (authToken && !providedHeaders.has("Authorization")) {
    providedHeaders.set("Authorization", `Bearer ${authToken}`);
  }

  const response = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    headers: providedHeaders,
    cache: "no-store"
  });

  if (!response.ok) {
    let detail = `API ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown; message?: unknown };
      if (typeof payload.detail === "string" && payload.detail.trim()) {
        detail = payload.detail.trim();
      } else if (typeof payload.message === "string" && payload.message.trim()) {
        detail = payload.message.trim();
      }
    } catch {
      const body = await response.text();
      if (body.trim()) {
        detail = body.trim();
      }
    }
    if (response.status === 401 && path !== "/api/auth/login") {
      clearAuthToken();
      dispatchAuthExpired();
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

function mapAuthSession(payload: ApiAuthSessionResponse): AuthSessionData {
  return {
    user: {
      id: payload.user.id,
      email: payload.user.email,
      role: payload.user.role,
      isActive: payload.user.is_active
    },
    expiresAt: payload.expires_at
  };
}

export async function login(email: string, password: string): Promise<AuthSessionData> {
  const payload = await fetchJson<ApiAuthLoginResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({
      email,
      password
    })
  });
  setAuthToken(payload.token);
  return mapAuthSession({
    user: payload.user,
    expires_at: payload.expires_at
  });
}

export async function logout(): Promise<void> {
  const token = getAuthToken();
  if (!token) {
    clearAuthToken();
    return;
  }
  try {
    const response = await fetchJson<ApiLogoutResponse>("/api/auth/logout", {
      method: "POST"
    });
    if (!response.ok) {
      throw new ApiError("Logout failed", 500);
    }
  } finally {
    clearAuthToken();
  }
}

export async function getAuthSession(): Promise<AuthSessionData> {
  const payload = await fetchJson<ApiAuthSessionResponse>("/api/auth/session");
  return mapAuthSession(payload);
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
  confirmNewPassword: string
): Promise<void> {
  const payload = await fetchJson<ApiPasswordChangeResponse>("/api/auth/password", {
    method: "POST",
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
      confirm_new_password: confirmNewPassword
    })
  });
  if (!payload.ok) {
    throw new ApiError("Unable to change password.", 500);
  }
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
  const tradingStatus = payload.trading_status;
  return {
    equity: payload.equity,
    dailyPnl: payload.daily_pnl,
    totalPnl: payload.total_pnl,
    openPositions: payload.open_positions,
    systemStatus: payload.system_status,
    riskAlerts: payload.risk_alerts,
    tradingStatus: {
      signalProvider: tradingStatus?.signal_provider ?? "synthetic",
      tradingVenue: tradingStatus?.trading_venue ?? "alpaca",
      tradingMode: tradingStatus?.trading_mode ?? "disabled",
      polyTradingMode: tradingStatus?.poly_trading_mode ?? "disabled",
      alpacaTradingMode: tradingStatus?.alpaca_trading_mode ?? "disabled",
      polyDryRun: tradingStatus?.poly_dry_run ?? true,
      workerEnableTrading: tradingStatus?.worker_enable_trading ?? false,
      workerDryRun: tradingStatus?.worker_dry_run ?? true,
      paperTradingEnabled: tradingStatus?.paper_trading_enabled ?? false,
      liveTradingEnabled: tradingStatus?.live_trading_enabled ?? false,
      executionAdapter: tradingStatus?.execution_adapter ?? "alpaca_execution_disabled"
    }
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

export async function getStrategyAnalytics(
  source: AnalyticsSource = "execution"
): Promise<StrategyAnalyticsData> {
  const payload = await fetchJson<ApiStrategyAnalyticsResponse>(
    `/api/analytics/strategies?source=${source}`
  );
  return {
    generatedAt: payload.generated_at,
    dataSource: payload.data_source,
    aggregationScope: payload.aggregation_scope,
    runCount: payload.run_count,
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

export async function getPortfolioAnalytics(
  source: AnalyticsSource = "execution"
): Promise<PortfolioAnalyticsData> {
  const payload = await fetchJson<ApiPortfolioAnalyticsResponse>(
    `/api/analytics/portfolio?source=${source}`
  );
  return {
    generatedAt: payload.generated_at,
    dataSource: payload.data_source,
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

export async function getContextAnalytics(
  source: AnalyticsSource = "execution"
): Promise<ContextAnalyticsData> {
  const payload = await fetchJson<ApiContextAnalyticsResponse>(
    `/api/analytics/context?source=${source}`
  );
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
    dataSource: payload.data_source,
    bySymbol: payload.by_symbol.map(mapBucket),
    byTimeframe: payload.by_timeframe.map(mapBucket),
    byWeekday: payload.by_weekday.map(mapBucket),
    byHour: payload.by_hour.map(mapBucket),
    byRegime: payload.by_regime.map(mapBucket)
  };
}

export async function getSelectionStatus(): Promise<SelectionStatusData> {
  const payload = await fetchJson<ApiSelectionStatusResponse>("/api/selection/status");
  const mapScore = (item: ApiStrategyScore) => ({
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
  });
  return {
    generatedAt: payload.generated_at,
    regime: payload.regime,
    regimeSignals: payload.regime_signals,
    selectedStrategy: payload.selected_strategy,
    selectedScore: payload.selected_score,
    minimumScoreThreshold: payload.minimum_score_threshold,
    sizingMultiplier: payload.sizing_multiplier,
    allocationFraction: payload.allocation_fraction,
    candidates: payload.candidates.map(mapScore)
  };
}

export async function getWorkerExecutionStatus(): Promise<WorkerExecutionStatusData> {
  const payload = await fetchJson<ApiWorkerExecutionStatusResponse>("/api/worker/execution-status");
  const mapScore = (item: ApiStrategyScore) => ({
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
  });
  return {
    generatedAt: payload.generated_at,
    workerName: payload.worker_name,
    timeframe: payload.timeframe,
    universeMode: payload.universe_mode,
    dryRunEnabled: payload.dry_run_enabled,
    universeSymbols: payload.universe_symbols,
    scannedSymbols: payload.scanned_symbols,
    shortlistedSymbols: payload.shortlisted_symbols,
    allowMultiStrategyPerSymbol: payload.allow_multi_strategy_per_symbol,
    selectedSymbol: payload.selected_symbol,
    selectedStrategy: payload.selected_strategy,
    lastSelectedSymbol: payload.last_selected_symbol,
    lastSelectedStrategy: payload.last_selected_strategy,
    lastNoTradeReason: payload.last_no_trade_reason,
    symbolFilterReasons: payload.symbol_filter_reasons,
    activeStrategyBySymbol: payload.active_strategy_by_symbol,
    symbols: payload.symbols.map((item) => ({
      symbol: item.symbol,
      timeframe: item.timeframe,
      runId: item.run_id,
      updatedAt: item.updated_at,
      action: item.action,
      orderStatus: item.order_status,
      selectedStrategy: item.selected_strategy,
      activeStrategy: item.active_strategy,
      selectedScore: item.selected_score,
      noTradeReason: item.no_trade_reason,
      rejectionReasons: item.rejection_reasons,
      candidates: item.candidates.map(mapScore)
    }))
  };
}
