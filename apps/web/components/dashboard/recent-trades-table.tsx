import type { TradeRow } from "@/lib/types";
import { TableScrollArea } from "@/components/table/table-scroll-area";

type RecentTradesTableProps = {
  trades: TradeRow[];
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

export function RecentTradesTable({ trades }: RecentTradesTableProps) {
  return (
    <article className="glass-panel rounded-2xl p-4">
      <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
        Recent Trades
      </h3>
      {trades.length === 0 ? (
        <p className="mt-3 text-sm text-[var(--muted)]">
          No real trades yet. Paper trading is idle or no fills have been persisted.
        </p>
      ) : (
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
                      trade.realizedPnl >= 0 ? "text-[var(--accent)]" : "text-[var(--danger)]"
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
      )}
    </article>
  );
}
