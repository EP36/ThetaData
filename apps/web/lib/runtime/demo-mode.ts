const TRUE_VALUES = new Set(["1", "true", "yes", "on"]);

/**
 * Return whether UI demo/mock mode is enabled.
 *
 * Demo mode must be explicitly enabled with NEXT_PUBLIC_DEMO_MODE=true.
 * Production deployments should keep this false/unset.
 */
export function isDemoModeEnabled(): boolean {
  const rawValue = (process.env.NEXT_PUBLIC_DEMO_MODE ?? "").trim().toLowerCase();
  return TRUE_VALUES.has(rawValue);
}
