import type { RiskEvent, RiskStatusData } from "@/lib/types";

export const mockRiskStatus: RiskStatusData = {
  maxDailyLoss: 2_000,
  currentDrawdown: 0.012,
  maxPositionSize: 1.0,
  grossExposure: 0.42,
  killSwitchEnabled: false,
  rejectedOrders: ["outside_trading_hours"]
};

export const mockRiskEvents: RiskEvent[] = [
  {
    timestamp: "2026-04-01T13:11:00Z",
    reason: "outside_trading_hours",
    severity: "warning"
  },
  {
    timestamp: "2026-04-01T14:50:00Z",
    reason: "max_position_size_exceeded",
    severity: "warning"
  }
];
