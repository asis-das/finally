"use client";

import { Panel } from "./Panel";
import { squarify } from "@/lib/treemap";
import { formatPercent, formatSignedCurrency } from "@/lib/format";
import type { Position } from "@/lib/types";

interface HeatmapProps {
  positions: Position[];
  selected: string | null;
  onSelect: (ticker: string) => void;
}

/** P&L percent → tile fill. Saturation carries magnitude; ±6% is full strength. */
function tileStyle(pnlPercent: number) {
  const strength = Math.min(Math.abs(pnlPercent) / 6, 1);
  const hue = pnlPercent >= 0 ? "var(--color-up)" : "var(--color-down)";
  const mix = 7 + strength * 33;
  return {
    backgroundColor: `color-mix(in srgb, ${hue} ${mix}%, var(--color-panel))`,
    borderColor: `color-mix(in srgb, ${hue} ${Math.round(24 + strength * 30)}%, transparent)`,
  };
}

export function Heatmap({ positions, selected, onSelect }: HeatmapProps) {
  const tiles = squarify(
    positions.map((position) => ({
      value: Math.max(position.market_value, 0),
      item: position,
    })),
    100,
    100,
  );

  return (
    <Panel title="Allocation" testId="portfolio-heatmap" bodyClassName="relative p-px">
      {tiles.length === 0 ? (
        <p className="flex h-full items-center justify-center px-4 text-center text-[12px] text-mute">
          No positions yet. Buy something and it shows up here, sized by weight.
        </p>
      ) : (
        tiles.map(({ item, x, y, w, h }) => {
          const compact = w < 16 || h < 22;
          return (
            <button
              type="button"
              key={item.ticker}
              data-testid={`heatmap-tile-${item.ticker}`}
              onClick={() => onSelect(item.ticker)}
              title={`${item.ticker} · ${formatSignedCurrency(item.unrealized_pnl)} (${formatPercent(item.unrealized_pnl_percent)})`}
              style={{
                position: "absolute",
                left: `${x}%`,
                top: `${y}%`,
                width: `${w}%`,
                height: `${h}%`,
                ...tileStyle(item.unrealized_pnl_percent),
              }}
              className={`flex flex-col items-start justify-center overflow-hidden border px-1.5 text-left transition-[filter] hover:brightness-125 ${
                selected === item.ticker ? "ring-1 ring-accent ring-inset" : ""
              }`}
            >
              <span className="truncate text-[12px] leading-tight font-semibold">
                {item.ticker}
              </span>
              {!compact && (
                <span className="num truncate text-[10.5px] leading-tight text-ink/80">
                  {formatPercent(item.unrealized_pnl_percent)}
                </span>
              )}
            </button>
          );
        })
      )}
    </Panel>
  );
}
