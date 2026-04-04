import Link from "next/link";

export default function HomePage() {
  return (
    <section className="space-y-5">
      <article className="glass-panel panel-animate rounded-[1.9rem] p-5 sm:p-6">
        <span className="ui-pill text-[var(--accent-strong)]">Research Workspace</span>
        <h2 className="page-title mt-4 font-semibold">Research + Paper Trading Console</h2>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-[var(--muted)]">
          This UI remains backend-driven and paper-only. The mobile-first layout keeps
          core operating data easy to scan without changing any trading behavior.
        </p>
        <div className="mt-6 flex flex-col gap-3 sm:flex-row">
          <Link href="/dashboard" className="ui-button ui-button-primary w-full sm:w-auto">
            Open Dashboard
          </Link>
          <Link href="/analytics" className="ui-button ui-button-subtle w-full sm:w-auto">
            View Analytics
          </Link>
        </div>
      </article>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <article className="glass-panel rounded-[1.5rem] p-4">
          <p className="ui-label">Mobile First</p>
          <p className="mt-3 text-lg font-semibold tracking-[-0.03em] text-[var(--text)]">
            Single-column on small screens
          </p>
        </article>
        <article className="glass-panel rounded-[1.5rem] p-4">
          <p className="ui-label">Navigation</p>
          <p className="mt-3 text-lg font-semibold tracking-[-0.03em] text-[var(--text)]">
            Bottom nav for core workflows
          </p>
        </article>
        <article className="glass-panel rounded-[1.5rem] p-4">
          <p className="ui-label">Data Views</p>
          <p className="mt-3 text-lg font-semibold tracking-[-0.03em] text-[var(--text)]">
            Cards first, tables second
          </p>
        </article>
        <article className="glass-panel rounded-[1.5rem] p-4">
          <p className="ui-label">Safety</p>
          <p className="mt-3 text-lg font-semibold tracking-[-0.03em] text-[var(--text)]">
            Existing trading logic unchanged
          </p>
        </article>
      </div>
    </section>
  );
}
