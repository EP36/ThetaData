"use client";

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
      <div className="mx-auto flex min-h-screen w-full max-w-[1180px] items-center justify-center px-4 py-8 sm:px-6 lg:px-8">
        <div className="glass-panel rounded-3xl px-6 py-5 text-sm text-[var(--muted)]">
          Checking session...
        </div>
      </div>
    );
  }

  if (protectedPath && !session) {
    return (
      <div className="mx-auto flex min-h-screen w-full max-w-[1180px] items-center justify-center px-4 py-8 sm:px-6 lg:px-8">
        <div className="glass-panel rounded-3xl px-6 py-5 text-sm text-[var(--danger)]">
          Session required. Redirecting to login.
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[1180px] flex-col px-4 pb-10 pt-5 sm:px-6 lg:px-8">
      <header className="glass-panel panel-animate sticky top-3 z-40 mb-6 flex flex-wrap items-center justify-between gap-4 rounded-3xl px-5 py-4 md:px-6">
        <div className="space-y-1">
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
        <TopNav
          userEmail={session?.user.email ?? null}
          userRole={session?.user.role ?? null}
          onLogout={handleLogout}
        />
      </header>
      <main className="flex-1 panel-animate pb-2">{children}</main>
    </div>
  );
}
