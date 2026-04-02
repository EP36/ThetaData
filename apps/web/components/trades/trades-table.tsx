import type { TradeRow } from "@/lib/types";

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
    <section className="glass-panel rounded-3xl p-4">
      <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
        Trades
      </h3>
      <div className="mt-3 overflow-x-auto">
        <table className="data-table text-sm">
          <thead>
            <tr>
              <th className="px-2 py-2">Timestamp</th>
              <th className="px-2 py-2">Symbol</th>
              <th className="px-2 py-2">Side</th>
              <th className="px-2 py-2">Quantity</th>
              <th className="px-2 py-2">Entry</th>
              <th className="px-2 py-2">Exit</th>
              <th className="px-2 py-2">Realized PnL</th>
              <th className="px-2 py-2">Strategy</th>
              <th className="px-2 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.timestamp}-${row.symbol}-${row.side}`}>
                <td className="px-2 py-2">{new Date(row.timestamp).toLocaleString()}</td>
                <td className="px-2 py-2 font-medium">{row.symbol}</td>
                <td className="px-2 py-2">{row.side}</td>
                <td className="px-2 py-2">{row.quantity}</td>
                <td className="px-2 py-2">{money(row.entryPrice)}</td>
                <td className="px-2 py-2">{money(row.exitPrice)}</td>
                <td
                  className={`px-2 py-2 font-semibold ${
                    row.realizedPnl >= 0 ? "text-[var(--accent)]" : "text-[var(--danger)]"
                  }`}
                >
                  {money(row.realizedPnl)}
                </td>
                <td className="px-2 py-2">{row.strategy}</td>
                <td className="px-2 py-2 capitalize">{row.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
