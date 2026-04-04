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
    <section className="glass-panel rounded-2xl p-4">
      <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
        Trades
      </h3>
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
                    row.realizedPnl >= 0 ? "text-[var(--accent)]" : "text-[var(--danger)]"
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
    </section>
  );
}
