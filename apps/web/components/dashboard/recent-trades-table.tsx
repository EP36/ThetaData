import type { TradeRow } from "@/lib/types";

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
    <article className="glass-panel rounded-3xl p-4">
      <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
        Recent Trades
      </h3>
      {trades.length === 0 ? (
        <p className="mt-3 text-sm text-[var(--muted)]">
          No real trades yet. Paper trading is idle or no fills have been persisted.
        </p>
      ) : (
        <div className="table-scroll">
          <table className="data-table text-sm">
            <thead>
              <tr>
                <th className="px-2 py-2">Time</th>
                <th className="px-2 py-2">Symbol</th>
                <th className="px-2 py-2">Side</th>
                <th className="px-2 py-2">Qty</th>
                <th className="px-2 py-2">Exit</th>
                <th className="px-2 py-2">PnL</th>
                <th className="px-2 py-2">Strategy</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade) => (
                <tr key={`${trade.timestamp}-${trade.symbol}-${trade.side}`}>
                  <td className="px-2 py-2">{new Date(trade.timestamp).toLocaleString()}</td>
                  <td className="px-2 py-2 font-medium">{trade.symbol}</td>
                  <td className="px-2 py-2">{trade.side}</td>
                  <td className="px-2 py-2">{formatNumber(trade.quantity)}</td>
                  <td className="px-2 py-2">{formatMoney(trade.exitPrice)}</td>
                  <td
                    className={`px-2 py-2 font-medium ${
                      trade.realizedPnl >= 0 ? "text-[var(--accent)]" : "text-[var(--danger)]"
                    }`}
                  >
                    {formatMoney(trade.realizedPnl)}
                  </td>
                  <td className="px-2 py-2">{trade.strategy}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}
