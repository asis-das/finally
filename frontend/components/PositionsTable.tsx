"use client";

import { Panel } from "./Panel";
import {
  formatCurrency,
  formatPercent,
  formatPrice,
  formatQuantity,
  formatSignedCurrency,
  toneClass,
} from "@/lib/format";
import type { PriceMap, Position } from "@/lib/types";

interface PositionsTableProps {
  positions: Position[];
  prices: PriceMap;
  selected: string | null;
  onSelect: (ticker: string) => void;
}

/** Re-values a position against the live tick so the table never lags the tape. */
function revalue(position: Position, price: number | undefined) {
  const last = typeof price === "number" ? price : position.current_price;
  const marketValue = position.quantity * last;
  const costBasis = position.quantity * position.avg_cost;
  const pnl = marketValue - costBasis;
  const pnlPercent = costBasis ? (pnl / costBasis) * 100 : 0;
  return { last, marketValue, pnl, pnlPercent };
}

export function PositionsTable({
  positions,
  prices,
  selected,
  onSelect,
}: PositionsTableProps) {
  return (
    <Panel
      title="Positions"
      testId="positions-table"
      aside={<span className="num text-[10.5px] text-mute">{positions.length}</span>}
      bodyClassName="overflow-auto"
    >
      {positions.length === 0 ? (
        <p className="p-3 text-[12px] text-dim">
          No open positions. Use the command bar below to place your first order.
        </p>
      ) : (
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10 bg-panel">
            <tr className="col-head border-b border-line">
              <th className="px-2.5 py-1.5 text-left font-semibold">Symbol</th>
              <th className="px-2.5 py-1.5 text-right font-semibold">Qty</th>
              <th className="px-2.5 py-1.5 text-right font-semibold">Avg cost</th>
              <th className="px-2.5 py-1.5 text-right font-semibold">Last</th>
              <th className="px-2.5 py-1.5 text-right font-semibold">Value</th>
              <th className="px-2.5 py-1.5 text-right font-semibold">Unrealized</th>
              <th className="px-2.5 py-1.5 text-right font-semibold">%</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((position) => {
              const { last, marketValue, pnl, pnlPercent } = revalue(
                position,
                prices[position.ticker]?.price,
              );
              const active = selected === position.ticker;
              return (
                <tr
                  key={position.ticker}
                  data-testid={`position-row-${position.ticker}`}
                  onClick={() => onSelect(position.ticker)}
                  className={`cursor-pointer border-b border-line/60 last:border-b-0 ${
                    active ? "bg-raised" : "hover:bg-raised/60"
                  }`}
                >
                  <td className="px-2.5 py-1.5 text-left text-[12.5px] font-semibold">
                    <span
                      className={`border-l-2 pl-1.5 ${
                        active ? "border-l-accent" : "border-l-transparent"
                      }`}
                    >
                      {position.ticker}
                    </span>
                  </td>
                  <td
                    data-testid={`position-qty-${position.ticker}`}
                    className="num px-2.5 py-1.5 text-right text-[12.5px]"
                  >
                    {formatQuantity(position.quantity)}
                  </td>
                  <td className="num px-2.5 py-1.5 text-right text-[12.5px] text-dim">
                    {formatPrice(position.avg_cost)}
                  </td>
                  <td className="num px-2.5 py-1.5 text-right text-[12.5px]">
                    {formatPrice(last)}
                  </td>
                  <td className="num px-2.5 py-1.5 text-right text-[12.5px]">
                    {formatCurrency(marketValue)}
                  </td>
                  <td
                    data-testid={`position-pnl-${position.ticker}`}
                    className={`num px-2.5 py-1.5 text-right text-[12.5px] ${toneClass(pnl)}`}
                  >
                    {formatSignedCurrency(pnl)}
                  </td>
                  <td className={`num px-2.5 py-1.5 text-right text-[12.5px] ${toneClass(pnl)}`}>
                    {formatPercent(pnlPercent)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
