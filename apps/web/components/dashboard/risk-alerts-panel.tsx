type RiskAlertsPanelProps = {
  alerts: string[];
};

export function RiskAlertsPanel({ alerts }: RiskAlertsPanelProps) {
  return (
    <article>
      <h3 className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">
        Risk Alerts
      </h3>
      <p className="mt-1 text-sm leading-6 text-[var(--muted)]">
        Current warnings and protection events surfaced from the backend summary.
      </p>
      {alerts.length === 0 ? (
        <p className="mt-3 text-sm text-[var(--muted)]">No active risk alerts.</p>
      ) : (
        <ul className="mt-4 space-y-3">
          {alerts.map((alert) => (
            <li
              key={alert}
              className="rounded-[1.1rem] border border-[var(--danger)]/30 bg-[color:color-mix(in_srgb,var(--danger),white_90%)] px-4 py-3 text-sm leading-6 text-[var(--danger)]"
            >
              {alert}
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}
