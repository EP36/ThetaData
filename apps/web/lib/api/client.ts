import type {
  BacktestFormInput,
  BacktestResultData,
  DashboardSummary,
  RiskStatusData,
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
      profitFactor: payload.metrics.profit_factor ?? 0
    },
    equityCurve: payload.equity_curve,
    drawdownCurve: payload.drawdown_curve,
    trades: payload.trades.map(mapTradeRow)
  };
}

export async function getStrategies(): Promise<StrategyConfig[]> {
  const payload = await fetchJson<Array<Omit<StrategyConfig, "parameters"> & { parameters: Record<string, number> }>>(
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
