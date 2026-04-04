import type { ReactNode } from "react";

type PageHeaderProps = {
  eyebrow: string;
  title: string;
  description?: string;
  meta?: ReactNode;
};

export function PageHeader({
  eyebrow,
  title,
  description,
  meta
}: PageHeaderProps) {
  return (
    <div className="px-1">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="ui-label">{eyebrow}</p>
          <h2 className="page-title mt-2 font-semibold">{title}</h2>
          {description ? (
            <p className="mt-1 hidden max-w-3xl text-sm leading-6 text-[var(--muted)] sm:block">
              {description}
            </p>
          ) : null}
        </div>
        {meta ? <div className="flex shrink-0 items-center">{meta}</div> : null}
      </div>
    </div>
  );
}
