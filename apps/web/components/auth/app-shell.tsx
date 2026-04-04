"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

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
        <div className="glass-panel rounded-2xl px-5 py-4 text-sm text-[var(--muted)]">
          Checking session...
        </div>
      </div>
    );
  }

  if (protectedPath && !session) {
    return (
      <div className="mx-auto flex min-h-screen w-full max-w-[1240px] items-center justify-center px-4 py-8 sm:px-6 xl:px-8">
        <div className="glass-panel rounded-2xl px-5 py-4 text-sm text-[var(--danger)]">
          Session required. Redirecting to login.
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[1240px] flex-col px-4 pb-7 pt-3 sm:px-6 xl:px-8">
      <header className="shell-header glass-panel panel-animate sticky top-2 z-40 mb-3 rounded-2xl px-3.5 py-2.5 md:px-4 md:py-3">
        <div className="flex flex-col gap-2 md:grid md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:items-center md:gap-3">
          <div className="min-w-0 space-y-0.5 md:justify-self-start">
            <p className="text-[0.58rem] font-semibold uppercase tracking-[0.24em] text-[var(--muted)]">
              Theta Data
            </p>
            <div className="flex flex-wrap items-center gap-1.5">
              <h1 className="text-base font-semibold tracking-[-0.02em] sm:text-lg">
                Trading Operations Console
              </h1>
              <span className="ui-pill border-[var(--accent-ring)] bg-[var(--accent-soft)] px-2 py-0.5 text-[0.58rem] text-[var(--accent-strong)]">
                Paper-Only
              </span>
            </div>
          </div>

          <div className="md:justify-self-center">
            <TopNav />
          </div>

          <div className="flex min-w-0 flex-wrap items-center justify-start gap-1.5 md:justify-end md:justify-self-end">
            <div className="hidden max-w-[14rem] items-center gap-2 rounded-full border border-[var(--line-soft)] bg-[var(--surface-soft)] px-2.5 py-1 text-xs text-[var(--muted)] sm:flex">
              <span className="truncate font-medium text-[var(--text)]">
                {session?.user.email ?? "Signed out"}
              </span>
              <span className="text-[10px] uppercase tracking-[0.12em]">
                {session?.user.role ?? "guest"}
              </span>
            </div>
            <Link
              href="/settings"
              className="ui-button ui-button-subtle px-2.5 py-1 text-xs"
            >
              Settings
            </Link>
            {session ? (
              <button
                type="button"
                onClick={() => void handleLogout()}
                className="ui-button ui-button-subtle px-2.5 py-1 text-xs"
              >
                Logout
              </button>
            ) : (
              <Link href="/login" className="ui-button ui-button-subtle px-2.5 py-1 text-xs">
                Login
              </Link>
            )}
            <span className="text-[10px] uppercase tracking-[0.12em] text-[var(--muted)] sm:hidden">
              {session?.user.role ?? "guest"}
            </span>
          </div>
        </div>
      </header>
      <main className="flex-1 panel-animate pb-1">{children}</main>
    </div>
  );
}
