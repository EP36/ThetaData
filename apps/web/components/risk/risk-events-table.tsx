import type { RiskEvent } from "@/lib/types";

type RiskEventsTableProps = {
  events: RiskEvent[];
};

export function RiskEventsTable({ events }: RiskEventsTableProps) {
  return (
    <article className="glass-panel rounded-2xl p-4">
      <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
        Risk Event Log
      </h3>
      <div className="table-scroll">
        <table className="data-table text-sm">
          <thead>
            <tr>
              <th className="px-2 py-2">Timestamp</th>
              <th className="px-2 py-2">Reason</th>
              <th className="px-2 py-2">Severity</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={`${event.timestamp}-${event.reason}`}>
                <td className="px-2 py-2">{new Date(event.timestamp).toLocaleString()}</td>
                <td className="px-2 py-2">{event.reason}</td>
                <td
                  className={`px-2 py-2 font-semibold ${
                    event.severity === "critical"
                      ? "text-[var(--danger)]"
                      : event.severity === "warning"
                        ? "text-[var(--warning-strong)]"
                        : "text-[var(--accent)]"
                  }`}
                >
                  {event.severity}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}
