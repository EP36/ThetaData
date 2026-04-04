type RiskMetricCardProps = {
  label: string;
  value: string;
  tone?: "neutral" | "warning" | "critical";
};

export function RiskMetricCard({
  label,
  value,
  tone = "neutral"
}: RiskMetricCardProps) {
  const toneClass =
    tone === "critical"
      ? "text-[var(--danger)]"
      : tone === "warning"
        ? "text-[var(--warning-strong)]"
        : "text-[var(--ink)]";
  const toneBorder =
    tone === "critical"
      ? "before:bg-[var(--danger)]"
      : tone === "warning"
        ? "before:bg-[var(--warning)]"
        : "before:bg-[var(--line)]";

  return (
    <article
      className={`glass-panel relative overflow-hidden rounded-[1.5rem] p-4 before:absolute before:inset-x-5 before:top-0 before:h-[3px] before:rounded-full ${toneBorder}`}
    >
      <p className="ui-label">{label}</p>
      <p className={`mt-3 text-[1.6rem] font-semibold tracking-[-0.03em] ${toneClass}`}>
        {value}
      </p>
    </article>
  );
}
