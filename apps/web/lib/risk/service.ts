import { mockRiskEvents, mockRiskStatus } from "@/lib/mock/risk";
import { getRiskStatus as getRiskStatusFromApi, triggerKillSwitch } from "@/lib/api/client";
import type { RiskEvent, RiskStatusData } from "@/lib/types";

let riskStatusStore: RiskStatusData = structuredClone(mockRiskStatus);
let riskEventStore: RiskEvent[] = structuredClone(mockRiskEvents);

export async function getRiskStatus(): Promise<RiskStatusData> {
  try {
    const fromApi = await getRiskStatusFromApi();
    riskStatusStore = structuredClone(fromApi);
    return fromApi;
  } catch {
    await new Promise((resolve) => {
      setTimeout(resolve, 160);
    });
    return structuredClone(riskStatusStore);
  }
}

export async function getRiskEvents(): Promise<RiskEvent[]> {
  await new Promise((resolve) => {
    setTimeout(resolve, 120);
  });
  return structuredClone(riskEventStore);
}

export async function triggerEmergencyStop(): Promise<RiskStatusData> {
  try {
    const killSwitchEnabled = await triggerKillSwitch(true);
    riskStatusStore = {
      ...riskStatusStore,
      killSwitchEnabled,
      rejectedOrders: [...riskStatusStore.rejectedOrders, "kill_switch_enabled"]
    };
  } catch {
    await new Promise((resolve) => {
      setTimeout(resolve, 180);
    });
    riskStatusStore = {
      ...riskStatusStore,
      killSwitchEnabled: true,
      rejectedOrders: [...riskStatusStore.rejectedOrders, "kill_switch_enabled"]
    };
  }

  riskEventStore = [
    {
      timestamp: new Date().toISOString(),
      reason: "manual_emergency_stop",
      severity: "critical"
    },
    ...riskEventStore
  ];
  return structuredClone(riskStatusStore);
}

export function resetRiskMockState(): void {
  riskStatusStore = structuredClone(mockRiskStatus);
  riskEventStore = structuredClone(mockRiskEvents);
}
