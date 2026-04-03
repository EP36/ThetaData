const PUBLIC_PATHS = new Set(["/", "/login"]);

export function isProtectedPath(pathname: string): boolean {
  return !PUBLIC_PATHS.has(pathname);
}

export function loginPath(pathname: string, reason?: string): string {
  const next = encodeURIComponent(pathname || "/dashboard");
  if (reason) {
    return `/login?next=${next}&reason=${encodeURIComponent(reason)}`;
  }
  return `/login?next=${next}`;
}
