"use client";

import { FormEvent, Suspense, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { ApiError, login } from "@/lib/api/client";
import { sanitizeNextPath } from "@/lib/auth/routes";

const DEFAULT_EMAIL = "";

function LoginPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = useMemo(() => {
    return sanitizeNextPath(searchParams.get("next"), "/dashboard");
  }, [searchParams]);

  const initialReason = useMemo(() => searchParams.get("reason"), [searchParams]);
  const [email, setEmail] = useState(DEFAULT_EMAIL);
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(initialReason);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email.trim(), password);
      router.replace(nextPath);
    } catch (nextError) {
      if (nextError instanceof ApiError && nextError.status === 429) {
        setError(nextError.message);
      } else if (nextError instanceof Error) {
        setError(nextError.message || "Login failed.");
      } else {
        setError("Login failed.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[520px] items-center justify-center px-4 py-12 sm:px-6">
      <section className="glass-panel w-full rounded-3xl p-6 sm:p-8">
        <p className="text-[0.66rem] font-semibold uppercase tracking-[0.26em] text-[var(--muted)]">
          Trauto
        </p>
        <h1 className="page-title mt-3 font-semibold">Admin Sign In</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          Single-user admin authentication is required for trading controls and sensitive analytics.
        </p>

        <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
          <label className="block space-y-2">
            <span className="text-xs uppercase tracking-[0.12em] text-[var(--muted)]">Email</span>
            <input
              className="w-full rounded-xl border border-[var(--line)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="username"
              required
            />
          </label>

          <label className="block space-y-2">
            <span className="text-xs uppercase tracking-[0.12em] text-[var(--muted)]">Password</span>
            <input
              className="w-full rounded-xl border border-[var(--line)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </label>

          {error ? (
            <p className="rounded-xl border border-[var(--danger)] bg-[color:color-mix(in_srgb,var(--danger),white_92%)] px-3 py-2 text-sm text-[var(--danger)]">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={submitting}
            className="ui-button ui-button-primary w-full justify-center"
          >
            {submitting ? "Signing in..." : "Sign In"}
          </button>
        </form>
      </section>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto flex min-h-screen w-full max-w-[520px] items-center justify-center px-4 py-12 sm:px-6">
          <section className="glass-panel w-full rounded-3xl p-6 text-sm text-[var(--muted)] sm:p-8">
            Loading login form...
          </section>
        </div>
      }
    >
      <LoginPageContent />
    </Suspense>
  );
}
