"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { BottomNav } from "@/components/navigation/bottom-nav";
import { TopNav } from "@/components/navigation/top-nav";
import { getAuthSession, logout } from "@/lib/api/client";
import { isAuthPath, isProtectedPath, loginPath } from "@/lib/auth/routes";
import { authExpiredEventName, clearAuthToken, getAuthToken } from "@/lib/auth/session";
import type { AuthSessionData } from "@/lib/types";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "/";
  const router = useRouter();
  const authPath = useMemo(() => isAuthPath(pathname), [pathname]);
  const protectedPath = useMemo(() => isProtectedPath(pathname), [pathname]);
  const currentView = useMemo(() => {
    if (pathname.startsWith("/dashboard")) {
      return "Dashboard";
    }
    if (pathname.startsWith("/analytics")) {
      return "Analytics";
    }
    if (pathname.startsWith("/backtests")) {
      return "Backtests";
    }
    if (pathname.startsWith("/strategies")) {
      return "Strategies";
    }
    if (pathname.startsWith("/risk")) {
      return "Risk";
    }
    if (pathname.startsWith("/trades")) {
      return "Trades";
    }
    if (pathname.startsWith("/settings")) {
      return "Settings";
    }
    return "Workspace";
  }, [pathname]);
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
          if (authPath) {
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
  }, [authPath, pathname, protectedPath, router]);

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

  if (authPath) {
    return <main className="min-h-screen">{children}</main>;
  }

  if (checkingSession && protectedPath) {
    return (
      <div className="mx-auto flex min-h-screen w-full max-w-[1240px] items-center justify-center px-4 py-8 sm:px-6 xl:px-8">
        <div className="glass-panel rounded-[1.5rem] px-5 py-4 text-sm text-[var(--muted)]">
          Checking session...
        </div>
      </div>
    );
  }

  if (protectedPath && !session) {
    return (
      <div className="mx-auto flex min-h-screen w-full max-w-[1240px] items-center justify-center px-4 py-8 sm:px-6 xl:px-8">
        <div className="glass-panel rounded-[1.5rem] px-5 py-4 text-sm text-[var(--danger)]">
          Session required. Redirecting to login.
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[1320px] flex-col px-3 pb-[6.75rem] pt-3 sm:px-5 md:pb-8 xl:px-8">
      <header className="shell-header glass-panel panel-animate sticky top-3 z-40 mb-4 rounded-[1.5rem] px-4 py-3 sm:px-5 sm:py-4">
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-[0.62rem] font-semibold uppercase tracking-[0.24em] text-[var(--muted)]">
                  Trauto
                </p>
                <span className="ui-pill border-[var(--accent-ring)] bg-[var(--accent-soft)] text-[var(--accent-strong)]">
                  Paper-Only
                </span>
                <span className="rounded-full border border-[var(--line-soft)] bg-[var(--surface-soft)] px-3 py-1 text-[0.68rem] font-medium uppercase tracking-[0.14em] text-[var(--muted)]">
                  {currentView}
                </span>
              </div>
              <h1 className="mt-2 text-lg font-semibold tracking-[-0.03em] text-[var(--text)] sm:text-[1.45rem]">
                Trading Console
              </h1>
              <p className="mt-1 hidden max-w-2xl text-sm leading-6 text-[var(--muted)] md:block">
                Mobile-first monitoring for portfolio health, research outputs, and
                paper-trading controls.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2 lg:justify-end">
              <div className="hidden max-w-[18rem] items-center gap-2 rounded-full border border-[var(--line-soft)] bg-[var(--surface-soft)] px-3 py-2 text-xs text-[var(--muted)] sm:flex">
                <span className="truncate font-medium text-[var(--text)]">
                  {session?.user.email ?? "Signed out"}
                </span>
                <span className="rounded-full bg-[var(--panel)] px-2 py-1 text-[10px] uppercase tracking-[0.12em]">
                  {session?.user.role ?? "guest"}
                </span>
              </div>
              <Link href="/settings" className="ui-button ui-button-subtle hidden sm:inline-flex">
                Settings
              </Link>
              {session ? (
                <button
                  type="button"
                  onClick={() => void handleLogout()}
                  className="ui-button ui-button-subtle"
                >
                  Logout
                </button>
              ) : (
                <Link href="/login" className="ui-button ui-button-subtle">
                  Login
                </Link>
              )}
            </div>
          </div>

          <div className="hidden md:block">
            <TopNav variant="desktop" />
          </div>

          <div className="md:hidden">
            <TopNav variant="mobile-secondary" />
          </div>
        </div>
      </header>
      <main className="flex-1 panel-animate pb-2">{children}</main>
      <BottomNav />
    </div>
  );
}
