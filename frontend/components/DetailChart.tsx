"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import { Panel } from "./Panel";
import { useFlash } from "@/lib/useFlash";
import { formatPercent, formatPrice, toneClass } from "@/lib/format";
import type { PricePoint } from "@/lib/types";

interface DetailChartProps {
  ticker: string | null;
  points: PricePoint[];
  price: number | null;
}

export function DetailChart({ ticker, points, price }: DetailChartProps) {
  const flash = useFlash(price);

  const first = points.length ? points[0].p : null;
  const last = points.length ? points[points.length - 1].p : price;
  const change = first && last ? ((last - first) / first) * 100 : 0;
  const rising = change >= 0;
  const stroke = rising ? "var(--color-up)" : "var(--color-down)";

  const values = points.map((point) => point.p);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 1;
  const pad = (max - min || max * 0.01 || 1) * 0.25;

  return (
    <Panel
      title={ticker ? `${ticker} · session` : "Chart"}
      testId="detail-chart"
      aside={
        <span className={`num text-[11px] ${toneClass(change)}`}>
          {formatPercent(change)}
        </span>
      }
      bodyClassName="relative"
    >
      <div className="pointer-events-none absolute top-3 left-4 z-10 flex items-baseline gap-3">
        <span className="font-[family-name:var(--font-cond)] text-[15px] font-semibold tracking-[0.14em] text-dim">
          {ticker ?? "—"}
        </span>
        <span className="num text-[30px] leading-none font-medium">
          <span key={flash.nonce} className={`inline-block px-1 ${flash.className}`}>
            {formatPrice(price ?? last)}
          </span>
        </span>
      </div>

      {points.length < 2 ? (
        <p className="flex h-full items-center justify-center text-[12px] text-mute">
          {ticker
            ? "Collecting ticks — the session chart draws itself as prices arrive."
            : "Pick a symbol in the watchlist."}
        </p>
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={points} margin={{ top: 44, right: 56, bottom: 6, left: 8 }}>
            <defs>
              <linearGradient id="detail-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={stroke} stopOpacity={0.32} />
                <stop offset="100%" stopColor={stroke} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="var(--color-line)" vertical={false} />
            <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} hide />
            <YAxis
              domain={[min - pad, max + pad]}
              orientation="right"
              width={52}
              axisLine={false}
              tickLine={false}
              tick={{ fill: "var(--color-mute)", fontSize: 10, fontFamily: "var(--font-mono)" }}
              tickFormatter={(value: number) => value.toFixed(2)}
            />
            {price !== null && (
              <ReferenceLine
                y={price}
                stroke={stroke}
                strokeDasharray="3 3"
                strokeOpacity={0.7}
                ifOverflow="extendDomain"
              />
            )}
            <Area
              type="monotone"
              dataKey="p"
              stroke={stroke}
              strokeWidth={1.5}
              fill="url(#detail-fill)"
              isAnimationActive={false}
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </Panel>
  );
}
