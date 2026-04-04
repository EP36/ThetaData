type SummaryCardProps = {
  label: string;
  value: string;
  tone?: "default" | "positive" | "negative";
  meta?: string;
};

export function SummaryCard({
  label,
  value,
  tone = "default",
  meta
}: SummaryCardProps) {
  const toneClass =
    tone === "positive"
      ? "text-[var(--accent-strong)]"
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
      className={`glass-panel relative overflow-hidden rounded-[1.5rem] p-4 before:absolute before:inset-x-5 before:top-0 before:h-[3px] before:rounded-full sm:p-5 ${toneBorder}`}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="ui-label">{label}</p>
        {meta ? (
          <span className="hidden text-xs font-medium text-[var(--muted)] sm:block">{meta}</span>
        ) : null}
      </div>
      <p className={`mt-3 text-[1.85rem] font-semibold tracking-[-0.04em] ${toneClass}`}>
        {value}
      </p>
    </article>
  );
}
