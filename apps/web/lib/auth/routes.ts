const AUTH_PATHS = ["/login"];
const PUBLIC_PATHS = new Set(["/", ...AUTH_PATHS]);

export function normalizePathname(pathname: string): string {
  const raw = (pathname || "").trim();
  if (!raw) {
    return "/";
  }
  const prefixed = raw.startsWith("/") ? raw : `/${raw}`;
  const collapsed = prefixed.replace(/\/{2,}/g, "/");
  if (collapsed.length > 1 && collapsed.endsWith("/")) {
    return collapsed.slice(0, -1);
  }
  return collapsed;
}

export function isAuthPath(pathname: string): boolean {
  const normalized = normalizePathname(pathname);
  return AUTH_PATHS.some(
    (authPath) => normalized === authPath || normalized.startsWith(`${authPath}/`)
  );
}

export function isProtectedPath(pathname: string): boolean {
  const normalized = normalizePathname(pathname);
  if (PUBLIC_PATHS.has(normalized)) {
    return false;
  }
  if (isAuthPath(normalized)) {
    return false;
  }
  return true;
}

export function sanitizeNextPath(
  nextPath: string | null | undefined,
  fallback = "/dashboard"
): string {
  const safeFallback = normalizePathname(fallback) || "/dashboard";
  if (!nextPath || !nextPath.trim()) {
    return safeFallback;
  }

  let candidate = nextPath.trim();
  try {
    candidate = decodeURIComponent(candidate);
  } catch {
    // Keep the original value when decoding fails.
  }

  if (!candidate.startsWith("/") || candidate.startsWith("//")) {
    return safeFallback;
  }

  const [rawPath, rawQuery = ""] = candidate.split("?", 2);
  const normalizedPath = normalizePathname(rawPath);
  if (isAuthPath(normalizedPath)) {
    return safeFallback;
  }

  return rawQuery ? `${normalizedPath}?${rawQuery}` : normalizedPath;
}

export function loginPath(pathname: string, reason?: string): string {
  const params = new URLSearchParams();
  const redirectTarget = sanitizeNextPath(pathname);

  if (redirectTarget !== "/dashboard" || isProtectedPath(pathname)) {
    params.set("next", redirectTarget);
  }
  if (reason) {
    params.set("reason", reason);
  }

  const query = params.toString();
  return query ? `/login?${query}` : "/login";
}
