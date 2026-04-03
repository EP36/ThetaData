type StatusBadgeProps = {
  status: string;
};

const STATUS_LABELS: Record<string, string> = {
  paper_only_ready: "Paper Ready",
  paper_only_idle: "Paper Idle",
  kill_switch_enabled: "Kill Switch",
  backend_unavailable: "Backend Offline"
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const isDanger = status === "kill_switch_enabled";
  const isWarning = status === "backend_unavailable";
  const dotClass = isDanger
    ? "bg-[var(--danger)]"
    : isWarning
      ? "bg-[var(--warning)]"
      : "bg-[var(--accent)]";

  return (
    <span
      className={`ui-pill ${
        isDanger
          ? "border-[var(--danger)] bg-[color:color-mix(in_srgb,var(--danger),white_89%)] text-[var(--danger)]"
          : isWarning
            ? "border-[var(--warning)] bg-[color:color-mix(in_srgb,var(--warning),white_88%)] text-[var(--warning)]"
          : "border-[var(--accent-ring)] bg-[var(--accent-soft)] text-[var(--accent-strong)]"
      }`}
    >
      <span className={`mr-2 inline-block h-1.5 w-1.5 rounded-full ${dotClass}`} />
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}
