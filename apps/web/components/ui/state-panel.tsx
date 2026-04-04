import type { ReactNode } from "react";

type StatePanelProps = {
  title: string;
  description: string;
  tone?: "default" | "danger";
  action?: ReactNode;
};

export function StatePanel({
  title,
  description,
  tone = "default",
  action
}: StatePanelProps) {
  const toneClass =
    tone === "danger" ? "text-[var(--danger)]" : "text-[var(--muted)]";

  return (
    <section className="glass-panel rounded-[1.5rem] px-4 py-5 sm:px-5">
      <p className="ui-label">Status</p>
      <h2 className="mt-2 text-lg font-semibold tracking-[-0.02em] text-[var(--text)]">{title}</h2>
      <p className={`mt-2 text-sm leading-6 ${toneClass}`}>{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </section>
  );
}
