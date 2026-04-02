import Link from "next/link";

export default function HomePage() {
  return (
    <section className="glass-panel panel-animate rounded-3xl p-8 md:p-10">
      <span className="ui-pill text-[var(--accent-strong)]">Research Workspace</span>
      <h2 className="page-title mt-4 font-semibold">Research + Paper Trading Console</h2>
      <p className="mt-3 max-w-2xl text-sm text-[var(--muted)]">
        This UI is intentionally backend-driven and paper-only. Start from the dashboard
        to review portfolio state, risk posture, and recent execution activity.
      </p>
      <div className="mt-8">
        <Link
          href="/dashboard"
          className="ui-button ui-button-primary"
        >
          Open Dashboard
        </Link>
      </div>
    </section>
  );
}
