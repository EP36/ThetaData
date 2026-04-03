"use client";

import { FormEvent, useMemo, useState } from "react";

import { useTheme } from "@/components/theme/theme-provider";
import { changePassword } from "@/lib/api/client";
import type { ThemePreference } from "@/lib/theme";

const THEME_OPTIONS: Array<{
  value: ThemePreference;
  label: string;
  description: string;
}> = [
  {
    value: "light",
    label: "Light",
    description: "Use the light interface at all times."
  },
  {
    value: "dark",
    label: "Dark",
    description: "Use the dark interface at all times."
  },
  {
    value: "system",
    label: "System",
    description: "Follow your device color-scheme preference."
  }
];

const MIN_PASSWORD_LENGTH = 12;

export default function SettingsPage() {
  const { theme, resolvedTheme, setTheme } = useTheme();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordSuccess, setPasswordSuccess] = useState<string | null>(null);

  const resolvedThemeLabel = useMemo(
    () => (resolvedTheme === "dark" ? "Dark" : "Light"),
    [resolvedTheme]
  );

  const handlePasswordSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPasswordError(null);
    setPasswordSuccess(null);

    if (!currentPassword) {
      setPasswordError("Current password is required.");
      return;
    }
    if (newPassword.length < MIN_PASSWORD_LENGTH) {
      setPasswordError(
        `New password must be at least ${MIN_PASSWORD_LENGTH} characters.`
      );
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError("New password confirmation does not match.");
      return;
    }

    setSavingPassword(true);
    try {
      await changePassword(currentPassword, newPassword, confirmPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordSuccess("Password updated successfully.");
    } catch (error) {
      if (error instanceof Error && error.message) {
        setPasswordError(error.message);
      } else {
        setPasswordError("Unable to update password.");
      }
    } finally {
      setSavingPassword(false);
    }
  };

  return (
    <section className="space-y-4">
      <div className="px-1">
        <h2 className="page-title font-semibold">Settings</h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Manage appearance preferences and account security controls.
        </p>
      </div>

      <article className="glass-panel rounded-2xl p-4 md:px-5 md:py-5">
        <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
          Appearance
        </h3>
        <p className="mt-2 text-sm text-[var(--muted)]">
          Current applied mode: <span className="font-semibold text-[var(--text)]">{resolvedThemeLabel}</span>
          {" "}({theme} preference).
        </p>

        <div className="mt-4 space-y-2">
          {THEME_OPTIONS.map((option) => (
            <label
              key={option.value}
              className="flex cursor-pointer items-start gap-3 rounded-xl border border-[var(--line)] bg-[var(--panel-soft)] px-3 py-3"
            >
              <input
                type="radio"
                name="theme"
                value={option.value}
                checked={theme === option.value}
                onChange={() => setTheme(option.value)}
                className="mt-0.5 h-4 w-4 accent-[var(--accent)]"
              />
              <span>
                <span className="block text-sm font-semibold">{option.label}</span>
                <span className="block text-xs text-[var(--muted)]">{option.description}</span>
              </span>
            </label>
          ))}
        </div>
      </article>

      <article className="glass-panel rounded-2xl p-4 md:px-5 md:py-5">
        <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
          Account Security
        </h3>
        <p className="mt-2 text-sm text-[var(--muted)]">
          Change your admin password. This action is authenticated and audit logged.
        </p>

        <form className="mt-4 space-y-3" onSubmit={handlePasswordSubmit}>
          <label className="block space-y-1">
            <span className="ui-label">Current Password</span>
            <input
              type="password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              autoComplete="current-password"
              className="ui-input"
              required
            />
          </label>

          <label className="block space-y-1">
            <span className="ui-label">New Password</span>
            <input
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              autoComplete="new-password"
              className="ui-input"
              minLength={MIN_PASSWORD_LENGTH}
              required
            />
          </label>

          <label className="block space-y-1">
            <span className="ui-label">Confirm New Password</span>
            <input
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              autoComplete="new-password"
              className="ui-input"
              minLength={MIN_PASSWORD_LENGTH}
              required
            />
          </label>

          {passwordError ? (
            <p className="rounded-xl border border-[var(--danger)] bg-[color:color-mix(in_srgb,var(--danger),white_92%)] px-3 py-2 text-sm text-[var(--danger)]">
              {passwordError}
            </p>
          ) : null}

          {passwordSuccess ? (
            <p className="rounded-xl border border-[var(--accent-ring)] bg-[var(--accent-soft)] px-3 py-2 text-sm text-[var(--accent-strong)]">
              {passwordSuccess}
            </p>
          ) : null}

          <div className="pt-1">
            <button
              type="submit"
              disabled={savingPassword}
              className="ui-button ui-button-primary"
            >
              {savingPassword ? "Updating..." : "Update Password"}
            </button>
          </div>
        </form>
      </article>
    </section>
  );
}
