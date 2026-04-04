"use client";

import { useMemo, useState } from "react";

import type { StrategyConfig, StrategyValidationErrors } from "@/lib/types";

type StrategyCardProps = {
  strategy: StrategyConfig;
  onSave: (
    strategyName: StrategyConfig["name"],
    payload: Partial<Pick<StrategyConfig, "status" | "parameters">>
  ) => Promise<StrategyValidationErrors>;
};

function formatStrategyName(value: StrategyConfig["name"]): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function StrategyCard({ strategy, onSave }: StrategyCardProps) {
  const [status, setStatus] = useState(strategy.status);
  const [parameters, setParameters] = useState<Record<string, string>>(
    Object.fromEntries(
      Object.entries(strategy.parameters).map(([key, value]) => [key, String(value)])
    )
  );
  const [errors, setErrors] = useState<StrategyValidationErrors>({});
  const [isSaving, setIsSaving] = useState(false);

  const parameterTypes = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(strategy.parameters).map(([key, value]) => [key, typeof value])
      ) as Record<string, "number" | "string">,
    [strategy.parameters]
  );

  const parsedParameters = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(parameters).map(([key, value]) => [
          key,
          parameterTypes[key] === "number" ? Number(value) : value
        ])
      ),
    [parameterTypes, parameters]
  );

  const handleSave = async () => {
    setIsSaving(true);
    const nextErrors = await onSave(strategy.name, {
      status,
      parameters: parsedParameters
    });
    setErrors(nextErrors);
    setIsSaving(false);
  };

  return (
    <article className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold tracking-[-0.03em] text-[var(--text)]">
              {formatStrategyName(strategy.name)}
            </h3>
            <span
              className={`ui-pill ${
                status === "enabled"
                  ? "border-[var(--accent-ring)] bg-[var(--accent-soft)] text-[var(--accent-strong)]"
                  : "border-[var(--line-soft)] text-[var(--muted)]"
              }`}
            >
              {status}
            </span>
          </div>
          <p className="mt-2 text-sm leading-6 text-[var(--muted)]">{strategy.description}</p>
        </div>
        <label className="block w-full sm:w-[12rem]">
          <span className="ui-label">Status</span>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as StrategyConfig["status"])}
            className="ui-select mt-1 text-sm"
          >
            <option value="enabled">Enabled</option>
            <option value="disabled">Disabled</option>
          </select>
        </label>
      </header>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        {Object.entries(parameters).map(([key, value]) => (
          <label
            key={key}
            className="flex flex-col gap-1 rounded-[1.1rem] border border-[var(--line-soft)] bg-[var(--panel-soft)] p-3 text-sm"
          >
            <span className="ui-label">{key}</span>
            <input
              value={value}
              onChange={(event) =>
                setParameters((previous) => ({ ...previous, [key]: event.target.value }))
              }
              className={`ui-input ${
                errors[key] ? "border-[var(--danger)] focus:border-[var(--danger)]" : ""
              }`}
            />
            {errors[key] ? (
              <span className="text-xs text-[var(--danger)]">{errors[key]}</span>
            ) : null}
          </label>
        ))}
      </div>

      {errors.root ? (
        <p className="mt-4 rounded-2xl border border-[var(--danger)] bg-[color:color-mix(in_srgb,var(--danger),white_92%)] px-3 py-2 text-sm text-[var(--danger)]">
          {errors.root}
        </p>
      ) : null}

      <div className="mt-5">
        <button
          type="button"
          onClick={handleSave}
          disabled={isSaving}
          className="ui-button ui-button-primary w-full sm:w-auto"
        >
          {isSaving ? "Saving..." : "Save Strategy"}
        </button>
      </div>
    </article>
  );
}
