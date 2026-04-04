import type { ReactNode } from "react";

type CollapsibleSectionProps = {
  title: string;
  description?: string;
  meta?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
  className?: string;
};

export function CollapsibleSection({
  title,
  description,
  meta,
  defaultOpen = false,
  children,
  className
}: CollapsibleSectionProps) {
  return (
    <details
      open={defaultOpen}
      className={`glass-panel group rounded-[1.5rem] ${className ?? ""}`}
    >
      <summary className="collapsible-summary flex cursor-pointer list-none items-start justify-between gap-4 px-4 py-4 sm:px-5">
        <div className="min-w-0">
          <p className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">{title}</p>
          {description ? (
            <p className="mt-1 text-sm leading-6 text-[var(--muted)]">{description}</p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {meta}
          <span className="flex h-10 w-10 items-center justify-center rounded-full border border-[var(--line-soft)] bg-[var(--surface-soft)] text-[var(--muted)] transition-transform duration-200 group-open:rotate-45">
            <span className="text-xl leading-none">+</span>
          </span>
        </div>
      </summary>
      <div className="border-t border-[var(--line-soft)] px-4 py-4 sm:px-5 sm:py-5">
        {children}
      </div>
    </details>
  );
}
