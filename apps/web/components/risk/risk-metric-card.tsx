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

  return (
    <article className="glass-panel rounded-2xl p-3">
      <p className="text-xs uppercase tracking-[0.12em] text-[var(--muted)]">{label}</p>
      <p className={`mt-1 text-xl font-semibold ${toneClass}`}>{value}</p>
    </article>
  );
}
