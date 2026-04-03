"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { TopNav } from "@/components/navigation/top-nav";
import { getAuthSession, logout } from "@/lib/api/client";
import { isProtectedPath, loginPath } from "@/lib/auth/routes";
import { authExpiredEventName, clearAuthToken, getAuthToken } from "@/lib/auth/session";
import type { AuthSessionData } from "@/lib/types";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "/";
  const router = useRouter();
  const protectedPath = useMemo(() => isProtectedPath(pathname), [pathname]);
  const [session, setSession] = useState<AuthSessionData | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function syncSession() {
      const token = getAuthToken();
      if (!token) {
        if (!cancelled) {
          setSession(null);
          setCheckingSession(false);
          if (protectedPath) {
            router.replace(loginPath(pathname));
          }
        }
        return;
      }

      setCheckingSession(true);
      try {
        const activeSession = await getAuthSession();
        if (!cancelled) {
          setSession(activeSession);
          if (pathname === "/login") {
            router.replace("/dashboard");
          }
        }
      } catch (error) {
        clearAuthToken();
        if (!cancelled) {
          setSession(null);
          if (protectedPath) {
            const reason =
              error instanceof Error && error.message
                ? error.message
                : "Session expired";
            router.replace(loginPath(pathname, reason));
          }
        }
      } finally {
        if (!cancelled) {
          setCheckingSession(false);
        }
      }
    }

    void syncSession();
    return () => {
      cancelled = true;
    };
  }, [pathname, protectedPath, router]);

  useEffect(() => {
    const eventName = authExpiredEventName();
    const handleExpired = () => {
      setSession(null);
      clearAuthToken();
      if (isProtectedPath(pathname)) {
        router.replace(loginPath(pathname, "Session expired"));
      }
    };
    window.addEventListener(eventName, handleExpired);
    return () => {
      window.removeEventListener(eventName, handleExpired);
    };
  }, [pathname, router]);

  const handleLogout = async () => {
    await logout();
    setSession(null);
    router.replace("/login");
  };

  if (pathname === "/login") {
    return <main className="min-h-screen">{children}</main>;
  }

  if (checkingSession && protectedPath) {
    return (
      <div className="mx-auto flex min-h-screen w-full max-w-[1320px] items-center justify-center px-4 py-8 sm:px-6 xl:px-8">
        <div className="glass-panel rounded-3xl px-6 py-5 text-sm text-[var(--muted)]">
          Checking session...
        </div>
      </div>
    );
  }

  if (protectedPath && !session) {
    return (
      <div className="mx-auto flex min-h-screen w-full max-w-[1320px] items-center justify-center px-4 py-8 sm:px-6 xl:px-8">
        <div className="glass-panel rounded-3xl px-6 py-5 text-sm text-[var(--danger)]">
          Session required. Redirecting to login.
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[1320px] flex-col px-4 pb-8 pt-4 sm:px-6 xl:px-8">
      <header className="glass-panel panel-animate sticky top-3 z-40 mb-5 rounded-3xl px-4 py-4 md:px-6 md:py-5">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 space-y-1">
              <p className="text-[0.66rem] font-semibold uppercase tracking-[0.26em] text-[var(--muted)]">
                Theta Data
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-lg font-semibold tracking-[-0.02em] sm:text-xl">
                  Trading Operations Console
                </h1>
                <span className="ui-pill border-[var(--accent-ring)] bg-[var(--accent-soft)] text-[var(--accent-strong)]">
                  Paper-Only
                </span>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-end gap-2 rounded-2xl border border-[var(--line)] bg-[var(--panel-soft)] px-3 py-2">
              <div className="min-w-[10rem] text-right leading-tight md:min-w-[12rem]">
                <p className="text-xs font-medium text-[var(--text)]">
                  {session?.user.email ?? "Signed out"}
                </p>
                <p className="text-[10px] uppercase tracking-[0.12em] text-[var(--muted)]">
                  {session?.user.role ?? "guest"}
                </p>
              </div>
              <Link
                href="/settings"
                className="ui-button ui-button-subtle px-3 py-1 text-xs"
              >
                Settings
              </Link>
              {session ? (
                <button
                  type="button"
                  onClick={() => void handleLogout()}
                  className="ui-button ui-button-subtle px-3 py-1 text-xs"
                >
                  Logout
                </button>
              ) : (
                <Link href="/login" className="ui-button ui-button-subtle px-3 py-1 text-xs">
                  Login
                </Link>
              )}
            </div>
          </div>
          <TopNav />
        </div>
      </header>
      <main className="flex-1 panel-animate pb-1">{children}</main>
    </div>
  );
}
