type StatusBadgeProps = {
  status: string;
};

const STATUS_LABELS: Record<string, string> = {
  paper_only_ready: "Paper Ready",
  paper_only_idle: "Paper Idle",
  kill_switch_enabled: "Kill Switch"
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const isDanger = status === "kill_switch_enabled";
  const dotClass = isDanger ? "bg-[var(--danger)]" : "bg-[var(--accent)]";

  return (
    <span
      className={`ui-pill ${
        isDanger
          ? "border-[var(--danger)] bg-[color:color-mix(in_srgb,var(--danger),white_89%)] text-[var(--danger)]"
          : "border-[rgba(15,119,103,0.26)] bg-[var(--accent-soft)] text-[var(--accent-strong)]"
      }`}
    >
      <span className={`mr-2 inline-block h-1.5 w-1.5 rounded-full ${dotClass}`} />
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}
