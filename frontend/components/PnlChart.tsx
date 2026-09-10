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
import { formatCurrency, formatPercent, toneClass } from "@/lib/format";
import type { Snapshot } from "@/lib/types";

interface PnlChartProps {
  snapshots: Snapshot[];
  liveValue: number | null;
}

export function PnlChart({ snapshots, liveValue }: PnlChartProps) {
  const series = snapshots.map((snapshot, index) => ({
    index,
    value: snapshot.total_value,
    at: snapshot.recorded_at,
  }));
  if (liveValue !== null && series.length > 0) {
    series.push({ index: series.length, value: liveValue, at: "now" });
  }

  const opening = series.length ? series[0].value : 0;
  const latest = series.length ? series[series.length - 1].value : 0;
  const change = opening ? ((latest - opening) / opening) * 100 : 0;
  const rising = change >= 0;
  const stroke = rising ? "var(--color-up)" : "var(--color-down)";

  const values = series.map((point) => point.value);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 1;
  const pad = (max - min || max * 0.005 || 1) * 0.3;

  return (
    <Panel
      title="Portfolio value"
      testId="pnl-chart"
      aside={
        <span className={`num text-[11px] ${toneClass(change)}`}>
          {formatPercent(change)}
        </span>
      }
    >
      {series.length < 2 ? (
        <p className="flex h-full items-center justify-center px-4 text-center text-[12px] text-mute">
          The value line starts drawing after the first snapshot.
        </p>
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={series} margin={{ top: 10, right: 8, bottom: 6, left: 8 }}>
            <defs>
              <linearGradient id="pnl-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={stroke} stopOpacity={0.28} />
                <stop offset="100%" stopColor={stroke} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="var(--color-line)" vertical={false} />
            <XAxis dataKey="index" hide />
            <YAxis
              domain={[min - pad, max + pad]}
              width={62}
              axisLine={false}
              tickLine={false}
              tick={{ fill: "var(--color-mute)", fontSize: 10, fontFamily: "var(--font-mono)" }}
              tickFormatter={(value: number) => formatCurrency(value).replace("$", "")}
            />
            <ReferenceLine
              y={opening}
              stroke="var(--color-line-hi)"
              strokeDasharray="2 4"
            />
            <Area
              type="monotone"
              dataKey="value"
              stroke={stroke}
              strokeWidth={1.5}
              fill="url(#pnl-fill)"
              isAnimationActive={false}
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </Panel>
  );
}
