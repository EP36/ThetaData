import type { TradeRow } from "@/lib/types";
import { TableScrollArea } from "@/components/table/table-scroll-area";

type RecentTradesTableProps = {
  trades: TradeRow[];
  title?: string;
};

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

function formatMoney(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  }).format(value);
}

export function RecentTradesTable({
  trades,
  title = "Recent Trades"
}: RecentTradesTableProps) {
  return (
    <article className="rounded-[1.5rem]">
      <h3 className="text-base font-semibold tracking-[-0.02em] text-[var(--text)]">{title}</h3>
      <p className="mt-1 text-sm leading-6 text-[var(--muted)]">
        Most recent persisted fills with essential outcome data first.
      </p>
      {trades.length === 0 ? (
        <p className="mt-3 text-sm text-[var(--muted)]">
          No real trades yet. Paper trading is idle or no fills have been persisted.
        </p>
      ) : (
        <>
          <div className="mt-4 space-y-3 md:hidden">
            {trades.map((trade) => (
              <article
                key={`${trade.timestamp}-${trade.symbol}-${trade.side}`}
                className="rounded-[1.25rem] border border-[var(--line-soft)] bg-[var(--panel-soft)] p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-base font-semibold tracking-[-0.02em]">{trade.symbol}</p>
                      <span className="ui-pill px-2.5 py-1 text-[0.58rem]">{trade.side}</span>
                    </div>
                    <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
                      {new Date(trade.timestamp).toLocaleString()}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="ui-label">PnL</p>
                    <p
                      className={`mt-2 text-lg font-semibold tracking-[-0.03em] ${
                        trade.realizedPnl >= 0
                          ? "text-[var(--accent-strong)]"
                          : "text-[var(--danger)]"
                      }`}
                    >
                      {formatMoney(trade.realizedPnl)}
                    </p>
                  </div>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-2xl bg-[var(--panel)] px-3 py-2.5">
                    <p className="ui-label">Qty</p>
                    <p className="mt-2 font-semibold">{formatNumber(trade.quantity)}</p>
                  </div>
                  <div className="rounded-2xl bg-[var(--panel)] px-3 py-2.5">
                    <p className="ui-label">Exit</p>
                    <p className="mt-2 font-semibold">{formatMoney(trade.exitPrice)}</p>
                  </div>
                </div>

                <details className="mt-4 rounded-2xl border border-[var(--line-soft)] bg-[var(--panel)]">
                  <summary className="cursor-pointer list-none px-3 py-3 text-sm font-medium text-[var(--text)]">
                    More details
                  </summary>
                  <div className="grid gap-3 border-t border-[var(--line-soft)] px-3 py-3 text-sm text-[var(--muted)]">
                    <div className="flex items-center justify-between gap-3">
                      <span>Strategy</span>
                      <span className="text-right font-medium text-[var(--text)]">
                        {trade.strategy}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span>Status</span>
                      <span className="text-right font-medium capitalize text-[var(--text)]">
                        {trade.status}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span>Entry</span>
                      <span className="font-medium text-[var(--text)]">
                        {formatMoney(trade.entryPrice)}
                      </span>
                    </div>
                  </div>
                </details>
              </article>
            ))}
          </div>

          <div className="hidden md:block">
            <TableScrollArea minWidth={960}>
              <table className="data-table text-sm">
                <colgroup>
                  <col className="w-[24%]" />
                  <col className="w-[9%]" />
                  <col className="w-[9%]" />
                  <col className="w-[8%]" />
                  <col className="w-[12%]" />
                  <col className="w-[12%]" />
                  <col className="w-[26%]" />
                </colgroup>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th className="numeric">Qty</th>
                    <th className="numeric">Exit</th>
                    <th className="numeric">PnL</th>
                    <th>Strategy</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((trade) => (
                    <tr key={`${trade.timestamp}-${trade.symbol}-${trade.side}`}>
                      <td>{new Date(trade.timestamp).toLocaleString()}</td>
                      <td className="font-medium">{trade.symbol}</td>
                      <td>{trade.side}</td>
                      <td className="numeric">{formatNumber(trade.quantity)}</td>
                      <td className="numeric">{formatMoney(trade.exitPrice)}</td>
                      <td
                        className={`numeric font-medium ${
                          trade.realizedPnl >= 0
                            ? "text-[var(--accent-strong)]"
                            : "text-[var(--danger)]"
                        }`}
                      >
                        {formatMoney(trade.realizedPnl)}
                      </td>
                      <td>{trade.strategy}</td>
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
