"use client";

import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { BottomNav } from "@/components/navigation/bottom-nav";
import { TopNav } from "@/components/navigation/top-nav";
import { getAuthSession } from "@/lib/api/client";
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
        return;
      }
      router.replace("/login");
    };
    window.addEventListener(eventName, handleExpired);
    return () => {
      window.removeEventListener(eventName, handleExpired);
    };
  }, [pathname, router]);

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
    <div className="mx-auto flex min-h-screen w-full max-w-[1320px] flex-col px-3 pt-3 sm:px-5 xl:px-8">
      <header className="shell-header glass-panel panel-animate mb-4 rounded-[1.15rem] px-3 py-2.5 sm:rounded-[1.4rem] sm:px-4 sm:py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[0.6rem] font-semibold uppercase tracking-[0.22em] text-[var(--muted)]">
              Trauto
            </p>
            <h1 className="mt-0.5 text-base font-semibold tracking-[-0.03em] text-[var(--text)] sm:text-lg">
              Trading Console
            </h1>
          </div>
          <span className="ui-pill hidden sm:inline-flex">Paper-Only</span>
        </div>

        <div className="mt-3 hidden items-center justify-between gap-3 md:flex">
          <TopNav variant="desktop" />
          <div className="hidden max-w-[18rem] items-center gap-2 rounded-full border border-[var(--line-soft)] bg-[var(--surface-soft)] px-3 py-2 text-xs text-[var(--muted)] xl:flex">
            <span className="truncate font-medium text-[var(--text)]">
              {session?.user.email ?? "Signed out"}
            </span>
            <span className="rounded-full bg-[var(--panel)] px-2 py-1 text-[10px] uppercase tracking-[0.12em]">
              {session?.user.role ?? "guest"}
            </span>
          </div>
        </div>
      </header>
      <main className="flex-1 panel-animate pb-[calc(var(--mobile-footer-height)+env(safe-area-inset-bottom)+0.875rem)] md:pb-4">
        {children}
      </main>
      <BottomNav />
    </div>
  );
}
