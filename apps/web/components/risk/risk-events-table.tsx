import type { RiskEvent } from "@/lib/types";
import { TableScrollArea } from "@/components/table/table-scroll-area";

type RiskEventsTableProps = {
  events: RiskEvent[];
};

export function RiskEventsTable({ events }: RiskEventsTableProps) {
  return (
    <article className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
      <h3 className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">
        Risk Event Log
      </h3>
      <p className="mt-1 text-sm leading-6 text-[var(--muted)]">
        Time-ordered record of guardrail activity and risk-related events.
      </p>

      {events.length === 0 ? (
        <p className="mt-4 text-sm text-[var(--muted)]">No risk events recorded yet.</p>
      ) : (
        <>
          <div className="mt-4 space-y-3 md:hidden">
            {events.map((event) => (
              <article
                key={`${event.timestamp}-${event.reason}`}
                className="rounded-[1.25rem] border border-[var(--line-soft)] bg-[var(--panel-soft)] p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm font-medium leading-6 text-[var(--text)]">{event.reason}</p>
                  <span
                    className={`rounded-full px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.12em] ${
                      event.severity === "critical"
                        ? "bg-[color:color-mix(in_srgb,var(--danger),white_88%)] text-[var(--danger)]"
                        : event.severity === "warning"
                          ? "bg-[color:color-mix(in_srgb,var(--warning),white_88%)] text-[var(--warning-strong)]"
                          : "bg-[var(--accent-soft)] text-[var(--accent-strong)]"
                    }`}
                  >
                    {event.severity}
                  </span>
                </div>
                <p className="mt-3 text-xs leading-5 text-[var(--muted)]">
                  {new Date(event.timestamp).toLocaleString()}
                </p>
              </article>
            ))}
          </div>

          <div className="hidden md:block">
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
                              : "text-[var(--accent-strong)]"
                        }`}
                      >
                        {event.severity}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScrollArea>
          </div>
        </>
      )}
    </article>
  );
}
