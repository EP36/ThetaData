import { mockRiskEvents, mockRiskStatus } from "@/lib/mock/risk";
import { getRiskStatus as getRiskStatusFromApi, triggerKillSwitch } from "@/lib/api/client";
import { isDemoModeEnabled } from "@/lib/runtime/demo-mode";
import type { RiskEvent, RiskStatusData } from "@/lib/types";

const EMPTY_RISK_STATUS: RiskStatusData = {
  maxDailyLoss: 0,
  currentDrawdown: 0,
  maxPositionSize: 0,
  grossExposure: 0,
  killSwitchEnabled: false,
  rejectedOrders: []
};

let riskStatusStore: RiskStatusData = isDemoModeEnabled()
  ? structuredClone(mockRiskStatus)
  : structuredClone(EMPTY_RISK_STATUS);
let riskEventStore: RiskEvent[] = isDemoModeEnabled() ? structuredClone(mockRiskEvents) : [];

export async function getRiskStatus(): Promise<RiskStatusData> {
  try {
    const fromApi = await getRiskStatusFromApi();
    riskStatusStore = structuredClone(fromApi);
    return fromApi;
  } catch {
    if (!isDemoModeEnabled()) {
      throw new Error("Unable to load risk status from backend.");
    }
    return structuredClone(riskStatusStore);
  }
}

export async function getRiskEvents(): Promise<RiskEvent[]> {
  if (!isDemoModeEnabled()) {
    return [];
  }
  return structuredClone(riskEventStore);
}

export async function setEmergencyStop(enabled: boolean): Promise<RiskStatusData> {
  const demoModeEnabled = isDemoModeEnabled();
  try {
    await triggerKillSwitch(enabled);
    const refreshedStatus = await getRiskStatusFromApi();
    riskStatusStore = structuredClone(refreshedStatus);
  } catch (error) {
    if (!demoModeEnabled) {
      if (error instanceof Error && error.message) {
        throw error;
      }
      throw new Error("Unable to update kill switch state.");
    }
    riskStatusStore = { ...riskStatusStore, killSwitchEnabled: enabled };
  }

  if (demoModeEnabled) {
    riskEventStore = [
      {
        timestamp: new Date().toISOString(),
        reason: enabled ? "manual_emergency_stop_enabled" : "manual_emergency_stop_disabled",
        severity: enabled ? "critical" : "info"
      },
      ...riskEventStore
    ];
  }
  return structuredClone(riskStatusStore);
}

export async function triggerEmergencyStop(): Promise<RiskStatusData> {
  return setEmergencyStop(true);
}

export function resetRiskMockState(): void {
  riskStatusStore = isDemoModeEnabled()
    ? structuredClone(mockRiskStatus)
    : structuredClone(EMPTY_RISK_STATUS);
  riskEventStore = isDemoModeEnabled() ? structuredClone(mockRiskEvents) : [];
}
