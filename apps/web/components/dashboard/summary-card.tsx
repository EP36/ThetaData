type SummaryCardProps = {
  label: string;
  value: string;
  tone?: "default" | "positive" | "negative";
};

export function SummaryCard({ label, value, tone = "default" }: SummaryCardProps) {
  const toneClass =
    tone === "positive"
      ? "text-[var(--accent)]"
      : tone === "negative"
        ? "text-[var(--danger)]"
        : "text-[var(--ink)]";
  const toneBorder =
    tone === "positive"
      ? "before:bg-[var(--accent)]"
      : tone === "negative"
        ? "before:bg-[var(--danger)]"
        : "before:bg-[var(--line)]";

  return (
    <article
      className={`glass-panel relative rounded-2xl p-4 before:absolute before:inset-x-4 before:top-0 before:h-[3px] before:rounded-full ${toneBorder}`}
    >
      <p className="text-xs uppercase tracking-[0.2em] text-[var(--muted)]">{label}</p>
      <p className={`mt-2 text-2xl font-semibold tracking-[-0.01em] ${toneClass}`}>{value}</p>
    </article>
  );
}
