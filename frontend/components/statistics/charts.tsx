"use client";

/**
 * Inline-SVG charts for the Statistics and Analytics pages. No chart library.
 *
 * The chart measures its container and draws in CSS pixels, so axis text keeps
 * a readable size at every viewport width instead of scaling with a viewBox.
 * Unknown (null) values break lines and skip bars; they are never drawn as 0.
 */

import { useCallback, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { formatNumber, UNKNOWN } from "./format";

/** Categorical palette validated for the dark card surface (#211712). Assigned in order, never cycled by rank. */
export const SERIES_COLORS = ["#d3721e", "#009bdd", "#4aa651", "#ab72d3", "#ac8c00", "#da637a"];

const HEIGHT = 230;
const PAD = { top: 14, right: 16, bottom: 34 };
const TICK_FONT_WIDTH = 7;

export interface LineSeries {
  label: string;
  points: Array<{ x: number; y: number | null }>;
}

export interface BarSeries {
  label: string;
  values: Array<number | null>;
}

function seriesColor(index: number) {
  return SERIES_COLORS[Math.min(index, SERIES_COLORS.length - 1)];
}

/**
 * Measures the chart container. A callback ref (not an effect) so the observer
 * attaches whenever the container mounts, including after an empty state.
 */
function useContainerWidth() {
  const [width, setWidth] = useState(0);
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((element: HTMLDivElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!element) return;
    setWidth(element.clientWidth);
    observer.current = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.current.observe(element);
  }, []);
  return [ref, width] as const;
}

function niceStep(raw: number) {
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}

function yScaleTicks(maxValue: number, integerOnly: boolean, count = 4) {
  const max = maxValue > 0 ? maxValue : 1;
  const step = integerOnly ? Math.max(1, niceStep(max / count)) : niceStep(max / count);
  const top = Math.ceil(max / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let value = 0; value <= top + step / 2; value += step) ticks.push(value);
  const digits = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
  return { ticks, top, format: (value: number) => formatNumber(value, digits) };
}

function Legend({ labels, shape }: { labels: string[]; shape: "line" | "rect" }) {
  if (labels.length < 2) return null;
  return (
    <ul className="stats-legend" aria-label="Legend">
      {labels.map((label, index) => (
        <li key={`${label}-${index}`}>
          <span aria-hidden className="stats-legend-key" data-shape={shape} style={{ background: seriesColor(index) }} />
          <span>{label}</span>
        </li>
      ))}
    </ul>
  );
}

function ChartHead({ title, unit }: { title: string; unit: string }) {
  return (
    <figcaption className="stats-chart-head">
      <span className="stats-chart-title">{title}</span>
      <span className="stats-chart-unit">{unit}</span>
    </figcaption>
  );
}

function Tooltip({ title, rows, x, width }: {
  title: string;
  rows: Array<{ label: string; color: string; value: string }>;
  x: number;
  width: number;
}) {
  const flip = x > width * 0.6;
  return (
    <div
      className="stats-tooltip"
      role="presentation"
      style={flip ? { right: Math.max(0, width - x + 12), top: PAD.top } : { left: x + 12, top: PAD.top }}
    >
      <p className="stats-tooltip-title">{title}</p>
      {rows.map((row, index) => (
        <div key={`${row.label}-${index}`} className="stats-tooltip-row">
          <span aria-hidden className="stats-tooltip-key" style={{ background: row.color }} />
          <span className="stats-tooltip-label">{row.label}</span>
          <span className="stats-tooltip-value" data-unknown={row.value === UNKNOWN}>{row.value}</span>
        </div>
      ))}
    </div>
  );
}

function EmptyChart({ title, message }: { title: string; message: string }) {
  return (
    <figure className="stats-chart">
      <ChartHead title={title} unit="" />
      <p className="stats-chart-empty">{message}</p>
    </figure>
  );
}

export function LineChart({ title, series, xLabel, yLabel, formatX = (x) => formatNumber(x, 0), formatY = (y) => formatNumber(y, 2), emptyMessage = "No samples to chart." }: {
  title: string;
  series: LineSeries[];
  xLabel: string;
  yLabel: string;
  formatX?: (x: number) => string;
  formatY?: (y: number) => string;
  emptyMessage?: string;
}) {
  const [ref, width] = useContainerWidth();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const model = useMemo(() => {
    const xs = Array.from(new Set(series.flatMap((item) => item.points.map((point) => point.x)))).sort((a, b) => a - b);
    const ys = series.flatMap((item) => item.points.map((point) => point.y)).filter((y): y is number => y !== null && Number.isFinite(y));
    const lookups = series.map((item) => new Map(item.points.map((point) => [point.x, point.y] as const)));
    return { xs, ys, lookups };
  }, [series]);

  if (model.xs.length < 2 || model.ys.length === 0) return <EmptyChart title={title} message={emptyMessage} />;

  const minX = model.xs[0];
  const maxX = model.xs[model.xs.length - 1];
  const scale = yScaleTicks(Math.max(...model.ys), model.ys.every(Number.isInteger));
  const padLeft = Math.max(36, Math.max(...scale.ticks.map((tick) => scale.format(tick).length)) * TICK_FONT_WIDTH + 14);
  const plotWidth = Math.max(10, width - padLeft - PAD.right);
  const plotHeight = HEIGHT - PAD.top - PAD.bottom;
  const x = (value: number) => padLeft + ((value - minX) / Math.max(1e-9, maxX - minX)) * plotWidth;
  const y = (value: number) => PAD.top + plotHeight - (value / scale.top) * plotHeight;
  const baseline = y(0);
  const xTickCount = width < 380 ? 3 : width < 680 ? 4 : 5;
  const xTicks = Array.from({ length: xTickCount }, (_, index) => minX + ((maxX - minX) * index) / (xTickCount - 1));

  function onPointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    if (width === 0) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - bounds.left;
    const value = minX + ((px - padLeft) / plotWidth) * (maxX - minX);
    let best = 0;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (let index = 0; index < model.xs.length; index += 1) {
      const distance = Math.abs(model.xs[index] - value);
      if (distance < bestDistance) { bestDistance = distance; best = index; }
    }
    setHoverIndex(best);
  }

  const hoverX = hoverIndex === null ? null : model.xs[hoverIndex];

  return (
    <figure className="stats-chart" data-hovering={hoverIndex !== null}>
      <ChartHead title={title} unit={`${yLabel} over ${xLabel}`} />
      <div ref={ref} className="relative">
        {width > 0 && (
          <svg
            width={width}
            height={HEIGHT}
            role="img"
            aria-label={`${title}: ${yLabel} over ${xLabel}`}
            onPointerMove={onPointerMove}
            onPointerLeave={() => setHoverIndex(null)}
          >
            <g className="stats-chart-grid">
              {scale.ticks.slice(1).map((tick) => <line key={tick} x1={padLeft} x2={width - PAD.right} y1={y(tick)} y2={y(tick)} />)}
            </g>
            <line className="stats-chart-baseline" x1={padLeft} x2={width - PAD.right} y1={baseline} y2={baseline} />
            {series.map((item, index) => {
              const color = seriesColor(index);
              const segments: string[] = [];
              let segment = "";
              let last: { x: number; y: number } | null = null;
              for (const point of item.points) {
                if (point.y === null || !Number.isFinite(point.y)) { if (segment) segments.push(segment); segment = ""; continue; }
                segment += `${segment ? " L" : "M"} ${x(point.x).toFixed(1)} ${y(point.y).toFixed(1)}`;
                last = { x: point.x, y: point.y };
              }
              if (segment) segments.push(segment);
              return (
                <g key={`${item.label}-${index}`}>
                  {segments.map((d, part) => <path key={part} d={d} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />)}
                  {last && <circle className="stats-chart-ring" cx={x(last.x)} cy={y(last.y)} r={4} fill={color} />}
                </g>
              );
            })}
            {hoverX !== null && (
              <g>
                <line className="stats-chart-crosshair" x1={x(hoverX)} x2={x(hoverX)} y1={PAD.top} y2={baseline} />
                {series.map((item, index) => {
                  const value = model.lookups[index].get(hoverX);
                  if (value === null || value === undefined || !Number.isFinite(value)) return null;
                  return <circle key={`${item.label}-${index}`} className="stats-chart-ring" cx={x(hoverX)} cy={y(value)} r={4.5} fill={seriesColor(index)} />;
                })}
              </g>
            )}
            <g className="stats-chart-axis">
              {scale.ticks.map((tick) => <text key={tick} x={padLeft - 8} y={y(tick) + 4} textAnchor="end">{scale.format(tick)}</text>)}
              {xTicks.map((tick, index) => (
                <text key={index} x={x(tick)} y={HEIGHT - 10} textAnchor={index === 0 ? "start" : index === xTicks.length - 1 ? "end" : "middle"}>{formatX(tick)}</text>
              ))}
            </g>
          </svg>
        )}
        {hoverX !== null && width > 0 && (
          <Tooltip
            title={`${xLabel} ${formatX(hoverX)}`}
            x={x(hoverX)}
            width={width}
            rows={series.map((item, index) => {
              const value = model.lookups[index].get(hoverX);
              return { label: item.label, color: seriesColor(index), value: value === null || value === undefined ? UNKNOWN : formatY(value) };
            })}
          />
        )}
      </div>
      <Legend labels={series.map((item) => item.label)} shape="line" />
    </figure>
  );
}

function roundedBar(left: number, top: number, barWidth: number, barHeight: number) {
  const radius = Math.min(4, barWidth / 2, barHeight);
  const right = left + barWidth;
  const bottom = top + barHeight;
  if (radius <= 0) return `M${left} ${bottom} H${right} V${top} H${left} Z`;
  return `M${left} ${bottom} V${top + radius} Q${left} ${top} ${left + radius} ${top} H${right - radius} Q${right} ${top} ${right} ${top + radius} V${bottom} Z`;
}

/** Grouped vertical bars: one group per category, one bar per series. */
export function GroupedBarChart({ title, categories, series, yLabel, formatY = (y) => formatNumber(y, 2), emptyMessage = "No values to chart." }: {
  title: string;
  categories: string[];
  series: BarSeries[];
  yLabel: string;
  formatY?: (y: number) => string;
  emptyMessage?: string;
}) {
  const [ref, width] = useContainerWidth();
  const [hoverGroup, setHoverGroup] = useState<number | null>(null);
  const values = series.flatMap((item) => item.values).filter((value): value is number => value !== null && Number.isFinite(value));
  if (categories.length === 0 || values.length === 0) return <EmptyChart title={title} message={emptyMessage} />;

  const scale = yScaleTicks(Math.max(...values), values.every(Number.isInteger));
  const padLeft = Math.max(36, Math.max(...scale.ticks.map((tick) => scale.format(tick).length)) * TICK_FONT_WIDTH + 14);
  const plotWidth = Math.max(10, width - padLeft - PAD.right);
  const plotHeight = HEIGHT - PAD.top - PAD.bottom;
  const y = (value: number) => PAD.top + plotHeight - (value / scale.top) * plotHeight;
  const baseline = y(0);
  const groupWidth = plotWidth / categories.length;
  const gap = 2;
  const barWidth = Math.max(1, Math.min(24, (groupWidth * 0.72 - gap * (series.length - 1)) / series.length));
  const groupInner = barWidth * series.length + gap * (series.length - 1);
  const groupOffset = (groupWidth - groupInner) / 2;
  const labelCount = Math.max(2, Math.min(categories.length, Math.floor(plotWidth / 90)));
  const labelIndices = categories.length <= labelCount
    ? categories.map((_, index) => index)
    : Array.from(new Set(Array.from({ length: labelCount }, (_, step) => Math.round((step * (categories.length - 1)) / (labelCount - 1)))));

  function onPointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    if (width === 0) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - bounds.left;
    const index = Math.floor((px - padLeft) / groupWidth);
    setHoverGroup(index >= 0 && index < categories.length ? index : null);
  }

  return (
    <figure className="stats-chart" data-hovering={hoverGroup !== null}>
      <ChartHead title={title} unit={yLabel} />
      <div ref={ref} className="relative">
        {width > 0 && (
          <svg width={width} height={HEIGHT} role="img" aria-label={`${title}: ${yLabel}`} onPointerMove={onPointerMove} onPointerLeave={() => setHoverGroup(null)}>
            <g className="stats-chart-grid">
              {scale.ticks.slice(1).map((tick) => <line key={tick} x1={padLeft} x2={width - PAD.right} y1={y(tick)} y2={y(tick)} />)}
            </g>
            {hoverGroup !== null && <rect className="stats-chart-band" x={padLeft + hoverGroup * groupWidth} y={PAD.top} width={groupWidth} height={plotHeight} rx={4} />}
            {categories.map((category, groupIndex) => series.map((item, seriesIndex) => {
              const value = item.values[groupIndex];
              if (value === null || value === undefined || !Number.isFinite(value)) return null;
              const left = padLeft + groupIndex * groupWidth + groupOffset + seriesIndex * (barWidth + gap);
              const top = y(value);
              return (
                <path
                  key={`${category}-${item.label}-${seriesIndex}`}
                  className="stats-chart-bar"
                  data-hover={hoverGroup === groupIndex}
                  d={roundedBar(left, top, barWidth, Math.max(0, baseline - top))}
                  fill={seriesColor(seriesIndex)}
                />
              );
            }))}
            <line className="stats-chart-baseline" x1={padLeft} x2={width - PAD.right} y1={baseline} y2={baseline} />
            <g className="stats-chart-axis">
              {scale.ticks.map((tick) => <text key={tick} x={padLeft - 8} y={y(tick) + 4} textAnchor="end">{scale.format(tick)}</text>)}
              {labelIndices.map((index) => {
                const first = index === 0 && categories.length > labelCount;
                const last = index === categories.length - 1 && categories.length > labelCount;
                const anchorX = first ? padLeft + index * groupWidth : last ? padLeft + (index + 1) * groupWidth : padLeft + (index + 0.5) * groupWidth;
                return <text key={index} x={anchorX} y={HEIGHT - 10} textAnchor={first ? "start" : last ? "end" : "middle"}>{categories[index]}</text>;
              })}
            </g>
          </svg>
        )}
        {hoverGroup !== null && width > 0 && (
          <Tooltip
            title={categories[hoverGroup]}
            x={padLeft + (hoverGroup + 0.5) * groupWidth}
            width={width}
            rows={series.map((item, index) => {
              const value = item.values[hoverGroup];
              return { label: item.label, color: seriesColor(index), value: value === null || value === undefined ? UNKNOWN : formatY(value) };
            })}
          />
        )}
      </div>
      <Legend labels={series.map((item) => item.label)} shape="rect" />
    </figure>
  );
}
