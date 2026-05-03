"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getOperationalOverview } from "@/lib/api/client";
import type { OperationalOverview } from "@/lib/types";

const POLL_MS = 30_000;

type State = {
  data: OperationalOverview | null;
  loading: boolean;
  error: boolean;
  lastFetchedAt: Date | null;
};

export function useOperationalOverview(): State {
  const [state, setState] = useState<State>({
    data: null,
    loading: true,
    error: false,
    lastFetchedAt: null,
  });
  const mountedRef = useRef(true);

  const fetch = useCallback(async (isInitial = false) => {
    if (isInitial) {
      setState((s) => ({ ...s, loading: true, error: false }));
    }
    try {
      const data = await getOperationalOverview();
      if (mountedRef.current) {
        setState({ data, loading: false, error: false, lastFetchedAt: new Date() });
      }
    } catch {
      if (mountedRef.current) {
        setState((s) => ({ ...s, loading: false, error: true }));
      }
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void fetch(true);
    const id = setInterval(() => void fetch(false), POLL_MS);
    return () => {
      mountedRef.current = false;
      clearInterval(id);
    };
  }, [fetch]);

  return state;
}
