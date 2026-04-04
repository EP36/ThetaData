import type { TradeRow } from "@/lib/types";
import { TableScrollArea } from "@/components/table/table-scroll-area";

type TradesTableProps = {
  rows: TradeRow[];
};

function money(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  }).format(value);
}

export function TradesTable({ rows }: TradesTableProps) {
  return (
    <section className="glass-panel rounded-[1.5rem] p-4 sm:p-5">
      <h3 className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">
        Trades
      </h3>
      <p className="mt-1 text-sm leading-6 text-[var(--muted)]">
        Essential trade outcomes show first on mobile, with full details available on demand.
      </p>

      <div className="mt-4 space-y-3 md:hidden">
        {rows.map((row) => (
          <article
            key={`${row.timestamp}-${row.symbol}-${row.side}`}
            className="rounded-[1.25rem] border border-[var(--line-soft)] bg-[var(--panel-soft)] p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-base font-semibold tracking-[-0.02em]">{row.symbol}</p>
                  <span className="ui-pill px-2.5 py-1 text-[0.58rem]">{row.side}</span>
                  <span className="rounded-full border border-[var(--line-soft)] px-2.5 py-1 text-[0.68rem] capitalize text-[var(--muted)]">
                    {row.status}
                  </span>
                </div>
                <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
                  {new Date(row.timestamp).toLocaleString()}
                </p>
              </div>
              <div className="text-right">
                <p className="ui-label">PnL</p>
                <p
                  className={`mt-2 text-lg font-semibold tracking-[-0.03em] ${
                    row.realizedPnl >= 0
                      ? "text-[var(--accent-strong)]"
                      : "text-[var(--danger)]"
                  }`}
                >
                  {money(row.realizedPnl)}
                </p>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-2xl bg-[var(--panel)] px-3 py-2.5">
                <p className="ui-label">Strategy</p>
                <p className="mt-2 truncate font-semibold">{row.strategy}</p>
              </div>
              <div className="rounded-2xl bg-[var(--panel)] px-3 py-2.5">
                <p className="ui-label">Quantity</p>
                <p className="mt-2 font-semibold">{row.quantity}</p>
              </div>
            </div>

            <details className="mt-4 rounded-2xl border border-[var(--line-soft)] bg-[var(--panel)]">
              <summary className="cursor-pointer list-none px-3 py-3 text-sm font-medium text-[var(--text)]">
                View pricing details
              </summary>
              <div className="grid gap-3 border-t border-[var(--line-soft)] px-3 py-3 text-sm text-[var(--muted)]">
                <div className="flex items-center justify-between gap-3">
                  <span>Entry</span>
                  <span className="font-medium text-[var(--text)]">{money(row.entryPrice)}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>Exit</span>
                  <span className="font-medium text-[var(--text)]">{money(row.exitPrice)}</span>
                </div>
              </div>
            </details>
          </article>
        ))}
      </div>

      <div className="hidden md:block">
        <TableScrollArea minWidth={1120}>
          <table className="data-table text-sm">
            <colgroup>
              <col className="w-[19%]" />
              <col className="w-[8%]" />
              <col className="w-[8%]" />
              <col className="w-[8%]" />
              <col className="w-[11%]" />
              <col className="w-[11%]" />
              <col className="w-[13%]" />
              <col className="w-[16%]" />
              <col className="w-[6%]" />
            </colgroup>
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Symbol</th>
                <th>Side</th>
                <th className="numeric">Quantity</th>
                <th className="numeric">Entry</th>
                <th className="numeric">Exit</th>
                <th className="numeric">Realized PnL</th>
                <th>Strategy</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.timestamp}-${row.symbol}-${row.side}`}>
                  <td>{new Date(row.timestamp).toLocaleString()}</td>
                  <td className="font-medium">{row.symbol}</td>
                  <td>{row.side}</td>
                  <td className="numeric">{row.quantity}</td>
                  <td className="numeric">{money(row.entryPrice)}</td>
                  <td className="numeric">{money(row.exitPrice)}</td>
                  <td
                    className={`numeric font-semibold ${
                      row.realizedPnl >= 0
                        ? "text-[var(--accent-strong)]"
                        : "text-[var(--danger)]"
                    }`}
                  >
                    {money(row.realizedPnl)}
                  </td>
                  <td>{row.strategy}</td>
                  <td className="capitalize">{row.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScrollArea>
      </div>
    </section>
  );
}
