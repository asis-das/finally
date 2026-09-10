import type { PricePoint } from "@/lib/types";

interface SparklineProps {
  points: PricePoint[];
  width?: number;
  height?: number;
  className?: string;
}

/**
 * Hand-rolled SVG polyline — one per watchlist row, redrawn twice a second, so
 * a charting library here would be all overhead. Colour follows the session
 * move, not the last tick, so the row does not strobe.
 */
export function Sparkline({
  points,
  width = 68,
  height = 20,
  className = "",
}: SparklineProps) {
  if (points.length < 2) {
    return (
      <svg
        width={width}
        height={height}
        className={className}
        role="presentation"
        aria-hidden
      >
        <line
          x1={0}
          y1={height / 2}
          x2={width}
          y2={height / 2}
          stroke="var(--color-line-hi)"
          strokeWidth={1}
          strokeDasharray="2 3"
        />
      </svg>
    );
  }

  const values = points.map((point) => point.p);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = width / (points.length - 1);
  const pad = 1.5;
  const usable = height - pad * 2;

  const coords = values.map((value, index) => {
    const x = index * step;
    const y = pad + (1 - (value - min) / span) * usable;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  const rising = values[values.length - 1] >= values[0];
  const stroke = rising ? "var(--color-up)" : "var(--color-down)";

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={className}
      role="presentation"
      aria-hidden
    >
      <polyline
        points={coords.join(" ")}
        fill="none"
        stroke={stroke}
        strokeWidth={1.25}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
