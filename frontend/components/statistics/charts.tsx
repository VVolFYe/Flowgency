/**
 * Minimal inline-SVG charts for the statistics skeleton. No chart library.
 * Colours are placeholders exposed as CSS variables so the page can be restyled.
 */

import { formatNumber } from "./format";

export const SERIES_COLORS = [
  "var(--stat-series-1, #9aa5ab)",
  "var(--stat-series-2, #4fb3d9)",
  "var(--stat-series-3, #d9a24f)",
  "var(--stat-series-4, #b77fd9)",
  "var(--stat-series-5, #7fc97f)",
];

export interface LineSeries {
  label: string;
  points: Array<{ x: number; y: number | null }>;
}

const WIDTH = 640;
const HEIGHT = 220;
const PAD = { top: 12, right: 12, bottom: 28, left: 44 };

function Legend({ labels }: { labels: string[] }) {
  return (
    <ul className="statistics-legend mt-2 flex flex-wrap gap-4 text-xs">
      {labels.map((label, index) => (
        <li key={label} className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-2 w-3" style={{ background: SERIES_COLORS[index % SERIES_COLORS.length] }} />
          {label}
        </li>
      ))}
    </ul>
  );
}

export function LineChart({ title, series, xLabel, yLabel, formatX = (x) => formatNumber(x, 0) }: {
  title: string;
  series: LineSeries[];
  xLabel: string;
  yLabel: string;
  formatX?: (x: number) => string;
}) {
  const xs = series.flatMap((item) => item.points.map((point) => point.x));
  const ys = series.flatMap((item) => item.points.map((point) => point.y)).filter((y): y is number => y !== null);
  if (xs.length < 2 || ys.length === 0) return <p className="statistics-empty text-sm">No samples to chart.</p>;
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const maxY = Math.max(1, ...ys);
  const x = (value: number) => PAD.left + ((value - minX) / Math.max(1e-9, maxX - minX)) * (WIDTH - PAD.left - PAD.right);
  const y = (value: number) => HEIGHT - PAD.bottom - (value / maxY) * (HEIGHT - PAD.top - PAD.bottom);
  return (
    <figure className="statistics-chart">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={title} className="h-auto w-full">
        <line x1={PAD.left} x2={WIDTH - PAD.right} y1={y(0)} y2={y(0)} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={y(0)} stroke="currentColor" strokeOpacity={0.3} />
        {series.map((item, index) => {
          // Break the line at unknown (null) values instead of drawing them as zero.
          const paths: string[] = [];
          let path = "";
          for (const point of item.points) {
            if (point.y === null) { if (path) paths.push(path); path = ""; continue; }
            path += `${path ? " L" : "M"} ${x(point.x).toFixed(1)} ${y(point.y).toFixed(1)}`;
          }
          if (path) paths.push(path);
          return paths.map((d, part) => (
            <path key={`${item.label}-${part}`} d={d} fill="none" stroke={SERIES_COLORS[index % SERIES_COLORS.length]} strokeWidth={2} />
          ));
        })}
        <g fontSize={10} fill="currentColor" fillOpacity={0.7}>
          <text x={PAD.left - 6} y={PAD.top + 4} textAnchor="end">{formatNumber(maxY, 0)}</text>
          <text x={PAD.left - 6} y={y(0) + 4} textAnchor="end">0</text>
          <text x={PAD.left} y={HEIGHT - 8}>{formatX(minX)}</text>
          <text x={WIDTH - PAD.right} y={HEIGHT - 8} textAnchor="end">{formatX(maxX)}</text>
          <text x={WIDTH / 2} y={HEIGHT - 8} textAnchor="middle">{xLabel}</text>
        </g>
      </svg>
      <figcaption className="text-xs">{title} — y: {yLabel}</figcaption>
      <Legend labels={series.map((item) => item.label)} />
    </figure>
  );
}

export interface BarSeries {
  label: string;
  values: Array<number | null>;
}

/** Grouped vertical bars: one group per category, one bar per series. */
export function GroupedBarChart({ title, categories, series, yLabel }: {
  title: string;
  categories: string[];
  series: BarSeries[];
  yLabel: string;
}) {
  const values = series.flatMap((item) => item.values).filter((value): value is number => value !== null);
  if (categories.length === 0 || values.length === 0) return <p className="statistics-empty text-sm">No values to chart.</p>;
  const maxY = Math.max(1, ...values);
  const groupWidth = (WIDTH - PAD.left - PAD.right) / categories.length;
  const barWidth = Math.max(1, (groupWidth * 0.8) / series.length);
  const y = (value: number) => HEIGHT - PAD.bottom - (value / maxY) * (HEIGHT - PAD.top - PAD.bottom);
  return (
    <figure className="statistics-chart">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={title} className="h-auto w-full">
        <line x1={PAD.left} x2={WIDTH - PAD.right} y1={y(0)} y2={y(0)} stroke="currentColor" strokeOpacity={0.3} />
        {categories.map((category, groupIndex) => series.map((item, seriesIndex) => {
          const value = item.values[groupIndex];
          if (value === null || value === undefined) return null;
          const left = PAD.left + groupIndex * groupWidth + groupWidth * 0.1 + seriesIndex * barWidth;
          return (
            <rect key={`${category}-${item.label}`} x={left} y={y(value)} width={barWidth} height={y(0) - y(value)} fill={SERIES_COLORS[seriesIndex % SERIES_COLORS.length]}>
              <title>{`${item.label}, ${category}: ${formatNumber(value, 2)}`}</title>
            </rect>
          );
        }))}
        <g fontSize={10} fill="currentColor" fillOpacity={0.7}>
          <text x={PAD.left - 6} y={PAD.top + 4} textAnchor="end">{formatNumber(maxY, 0)}</text>
          <text x={PAD.left - 6} y={y(0) + 4} textAnchor="end">0</text>
          <text x={PAD.left} y={HEIGHT - 8}>{categories[0]}</text>
          <text x={WIDTH - PAD.right} y={HEIGHT - 8} textAnchor="end">{categories[categories.length - 1]}</text>
        </g>
      </svg>
      <figcaption className="text-xs">{title} — y: {yLabel}</figcaption>
      <Legend labels={series.map((item) => item.label)} />
    </figure>
  );
}
