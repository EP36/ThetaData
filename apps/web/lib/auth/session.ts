const AUTH_TOKEN_STORAGE_KEY = "theta_auth_token";
const AUTH_EXPIRED_EVENT = "theta-auth-expired";

function hasWindow(): boolean {
  return typeof window !== "undefined";
}

export function getAuthToken(): string | null {
  if (!hasWindow()) {
    return null;
  }
  const value = window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
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
