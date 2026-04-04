import type { RiskEvent } from "@/lib/types";
import { TableScrollArea } from "@/components/table/table-scroll-area";

type RiskEventsTableProps = {
  events: RiskEvent[];
};

export function RiskEventsTable({ events }: RiskEventsTableProps) {
  return (
    <article className="glass-panel rounded-2xl p-4">
      <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
        Risk Event Log
      </h3>
      <TableScrollArea minWidth={760}>
        <table className="data-table text-sm">
          <colgroup>
            <col className="w-[28%]" />
            <col className="w-[54%]" />
            <col className="w-[18%]" />
          </colgroup>
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Reason</th>
              <th>Severity</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={`${event.timestamp}-${event.reason}`}>
                <td>{new Date(event.timestamp).toLocaleString()}</td>
                <td className="cell-wrap">{event.reason}</td>
                <td
                  className={`font-semibold ${
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
      </TableScrollArea>
    </article>
  );
}
