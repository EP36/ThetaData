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
    <article className="glass-panel rounded-2xl p-4 md:px-5">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-base font-semibold">{strategy.name}</h3>
          <p className="mt-1 text-sm text-[var(--muted)]">{strategy.description}</p>
        </div>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value as StrategyConfig["status"])}
          className="ui-select text-sm"
        >
          <option value="enabled">Enabled</option>
          <option value="disabled">Disabled</option>
        </select>
      </header>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {Object.entries(parameters).map(([key, value]) => (
          <label key={key} className="flex flex-col gap-1 text-sm">
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

      {errors.root ? <p className="mt-2 text-xs text-[var(--danger)]">{errors.root}</p> : null}

      <div className="mt-4">
        <button
          type="button"
          onClick={handleSave}
          disabled={isSaving}
          className="ui-button ui-button-primary"
        >
          {isSaving ? "Saving..." : "Save Strategy"}
        </button>
      </div>
    </article>
  );
}
