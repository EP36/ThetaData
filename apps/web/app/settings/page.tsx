"use client";

import { FormEvent, useMemo, useState } from "react";

import { PageHeader } from "@/components/ui/page-header";
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
    <section className="space-y-5">
      <PageHeader
        eyebrow="Settings"
        title="Preferences & Security"
        description="Manage appearance preferences and account security controls."
      />

      <article className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
        <h3 className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">
          Appearance
        </h3>
        <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
          Current applied mode:{" "}
          <span className="font-semibold text-[var(--text)]">{resolvedThemeLabel}</span>
          {" "}({theme} preference).
        </p>

        <div className="mt-4 space-y-3">
          {THEME_OPTIONS.map((option) => (
            <label
              key={option.value}
              className="flex cursor-pointer items-start gap-3 rounded-[1.2rem] border border-[var(--line)] bg-[var(--panel-soft)] px-4 py-4"
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
                <span className="block text-sm font-semibold text-[var(--text)]">
                  {option.label}
                </span>
                <span className="mt-1 block text-sm leading-6 text-[var(--muted)]">
                  {option.description}
                </span>
              </span>
            </label>
          ))}
        </div>
      </article>

      <article className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
        <h3 className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">
          Account Security
        </h3>
        <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
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
              className="ui-button ui-button-primary w-full sm:w-auto"
            >
              {savingPassword ? "Updating..." : "Update Password"}
            </button>
          </div>
        </form>
      </article>
    </section>
  );
}
