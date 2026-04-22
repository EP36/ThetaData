type StatusBadgeProps = {
  status: string;
};

const STATUS_LABELS: Record<string, string> = {
  polymarket_live: "Polymarket Live",
  polymarket_dry_run: "Polymarket Dry Run",
  alpaca_live: "Alpaca Live",
  paper_only_ready: "Alpaca Paper Ready",
  paper_only_idle: "Alpaca Paper Idle",
  dry_run: "Dry Run",
  trading_disabled: "Trading Disabled",
  kill_switch_enabled: "Kill Switch",
  backend_unavailable: "Backend Offline"
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const isLive = status === "polymarket_live" || status === "alpaca_live";
  const isDanger = status === "kill_switch_enabled" || isLive;
  const isWarning = status === "backend_unavailable" || status === "trading_disabled";
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
