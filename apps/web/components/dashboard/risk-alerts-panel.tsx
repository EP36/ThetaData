type RiskAlertsPanelProps = {
  alerts: string[];
};

export function RiskAlertsPanel({ alerts }: RiskAlertsPanelProps) {
  return (
    <article className="glass-panel rounded-3xl p-4">
      <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
        Risk Alerts
      </h3>
      {alerts.length === 0 ? (
        <p className="mt-3 text-sm text-[var(--muted)]">No active risk alerts.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {alerts.map((alert) => (
            <li
              key={alert}
              className="rounded-xl border border-[var(--danger)]/30 bg-[color:color-mix(in_srgb,var(--danger),white_90%)] px-3 py-2 text-sm text-[var(--danger)]"
            >
              {alert}
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}
