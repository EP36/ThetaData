import type { BacktestFormInput, BacktestResultData } from "@/lib/types";
import { getBacktestResults } from "@/lib/api/client";
import { runMockBacktest } from "@/lib/mock/backtests";
import { isDemoModeEnabled } from "@/lib/runtime/demo-mode";

export async function runBacktest(
  request: BacktestFormInput
): Promise<BacktestResultData> {
  try {
    return await getBacktestResults(request);
  } catch (error) {
    if (!isDemoModeEnabled()) {
      throw error;
    }
    return runMockBacktest(request);
  }
}
