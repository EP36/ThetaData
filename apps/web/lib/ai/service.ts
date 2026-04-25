import { getAIAnalysisLog, getAIProposals, getAISignalParamsRaw } from "@/lib/api/client";
import type { AIInsightsData } from "@/lib/types";

export async function getAIInsightsData(): Promise<AIInsightsData> {
  const [signalParamsRaw, proposals, analysisLog] = await Promise.all([
    getAISignalParamsRaw(),
    getAIProposals(),
    getAIAnalysisLog(),
  ]);
  return {
    signalParams: signalParamsRaw.params ?? {},
    signalParamsMeta: {
      version: signalParamsRaw.version,
      updated_at: signalParamsRaw.updated_at ?? null,
      updated_by: signalParamsRaw.updated_by,
    },
    proposals: proposals ?? [],
    analysisLog: analysisLog ?? [],
  };
}
