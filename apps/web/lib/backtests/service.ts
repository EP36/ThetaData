import type { BacktestFormInput, BacktestResultData } from "@/lib/types";
import { getBacktestResults } from "@/lib/api/client";
import { runMockBacktest } from "@/lib/mock/backtests";

export async function runBacktest(
  request: BacktestFormInput
): Promise<BacktestResultData> {
  try {
    return await getBacktestResults(request);
  } catch {
    return runMockBacktest(request);
  }
}
