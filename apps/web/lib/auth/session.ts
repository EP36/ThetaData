const AUTH_TOKEN_STORAGE_KEY = "trauto_auth_token";
const LEGACY_AUTH_TOKEN_STORAGE_KEY = "theta_auth_token";
const AUTH_EXPIRED_EVENT = "trauto-auth-expired";

function hasWindow(): boolean {
  return typeof window !== "undefined";
}

export function getAuthToken(): string | null {
  if (!hasWindow()) {
    return null;
  }
  const value =
    window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)
    ?? window.localStorage.getItem(LEGACY_AUTH_TOKEN_STORAGE_KEY);
  if (
    value
    && value.trim()
    && window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) == null
  ) {
    window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, value);
    window.localStorage.removeItem(LEGACY_AUTH_TOKEN_STORAGE_KEY);
  }
  return value && value.trim() ? value : null;
}

export function setAuthToken(token: string): void {
  if (!hasWindow()) {
    return;
  }
  window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
}

export function clearAuthToken(): void {
  if (!hasWindow()) {
    return;
  }
  window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
  window.localStorage.removeItem(LEGACY_AUTH_TOKEN_STORAGE_KEY);
}

export function dispatchAuthExpired(): void {
  if (!hasWindow()) {
    return;
  }
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
}

export function authExpiredEventName(): string {
  return AUTH_EXPIRED_EVENT;
}
