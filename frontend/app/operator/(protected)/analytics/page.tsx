"use client";

import { ConnectionBadge, formatTime } from "@/components/simulation/simulation-workspace";
import { useSimulation, type HistoryPoint } from "@/components/simulation/simulation-provider";

const COLORS = ["#70e9a6", "#71c7ec", "#f0bc55", "#dc78f0", "#ff7f86", "#a4d47c"];

function LineChart({ points, series }: { points: HistoryPoint[]; series: Array<{ label: string; color: string; value: (point: HistoryPoint) => number | null }> }) {
  const width = 760;
  const height = 260;
  const padding = 30;
  const values = points.flatMap((point) => series.map((item) => item.value(point))).filter((value): value is number => value != null);
  if (points.length < 2 || values.length === 0) return <div className="grid h-[260px] place-items-center text-center text-sm text-[#6f808a]">Waiting for at least two real snapshots.</div>;
  const minTime = Math.min(...points.map((point) => point.simulationTimeS));
  const maxTime = Math.max(...points.map((point) => point.simulationTimeS));
  const maxValue = Math.max(1, ...values);
  const x = (time: number) => padding + ((time - minTime) / Math.max(1, maxTime - minTime)) * (width - padding * 2);
  const y = (value: number) => height - padding - (value / maxValue) * (height - padding * 2);
  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Current browser session chart" className="h-auto w-full overflow-visible">
        {[0, .25, .5, .75, 1].map((ratio) => <line key={ratio} x1={padding} x2={width - padding} y1={y(maxValue * ratio)} y2={y(maxValue * ratio)} stroke="rgba(255,255,255,.07)" />)}
        {series.map((item) => {
          const segments: string[] = [];
          let segment = "";
          points.forEach((point) => {
            const value = item.value(point);
            if (value == null) { if (segment) segments.push(segment); segment = ""; return; }
            segment += `${segment ? " L" : "M"} ${x(point.simulationTimeS).toFixed(1)} ${y(value).toFixed(1)}`;
          });
          if (segment) segments.push(segment);
          return segments.map((path, index) => <path key={`${item.label}-${index}`} d={path} fill="none" stroke={item.color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />);
        })}
        <text x={padding} y={height - 6} fill="#667781" fontSize="10">{formatTime(minTime)}</text><text x={width - padding} y={height - 6} textAnchor="end" fill="#667781" fontSize="10">{formatTime(maxTime)}</text><text x={padding - 8} y={padding + 3} textAnchor="end" fill="#667781" fontSize="10">{maxValue}</text><text x={padding - 8} y={height - padding + 3} textAnchor="end" fill="#667781" fontSize="10">0</text>
      </svg>
      <div className="mt-3 flex flex-wrap gap-4">{series.map((item) => <span key={item.label} className="flex items-center gap-2 text-[11px] text-[#8b9aa3]"><span className="h-2 w-2 rounded-full" style={{ background: item.color }} />{item.label}</span>)}</div>
    </div>
  );
}

function valueMax(values: Array<number | null>) {
  const known = values.filter((value): value is number => value != null);
  return known.length ? Math.max(...known) : null;
}

export default function OperatorAnalyticsPage() {
  const { history, status, snapshot, connection } = useSimulation();
  const approaches = Array.from(new Set(history.flatMap((point) => Object.keys(point.queues))));
  const currentVehicles = snapshot?.vehicles ? snapshot.vehicles.length : null;
  const maxVehicles = valueMax(history.map((point) => point.vehicleCount));
  const currentQueues = Object.values(snapshot?.queue_lengths_by_approach ?? {}).map((value) => value?.vehicles ?? null);
  const historicalQueues = history.flatMap((point) => Object.values(point.queues));
  const queueSeries = approaches.map((approach, index) => ({ label: approach, color: COLORS[index % COLORS.length], value: (point: HistoryPoint) => point.queues[approach] ?? null }));
  const vehicleSeries = [{ label: "Active vehicles", color: "#70e9a6", value: (point: HistoryPoint) => point.vehicleCount }];
  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#72e9a6]">Operator analytics</p><h1 className="mt-1 text-3xl font-semibold tracking-tight">Current browser session</h1><p className="mt-2 text-sm text-[#81909a]">Real WebSocket snapshots only. The series resets when a new <span className="font-mono">run_id</span> appears and is not persisted beyond this browser session.</p></div><ConnectionBadge connection={connection} stale={connection !== "connected" && snapshot !== null} /></div>
      <section className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {[
          ["Current vehicles", currentVehicles ?? "—"], ["Max vehicles", maxVehicles ?? "—"],
          ["Current max queue", valueMax(currentQueues) ?? "—"], ["Session max queue", valueMax(historicalQueues) ?? "—"],
          ["Simulation time", formatTime(snapshot?.simulation_time_s ?? status.simulation_time_s)],
        ].map(([label, value]) => <article key={label} className="rounded-2xl border border-white/[.07] bg-[#10171c] p-5"><p className="text-xs text-[#788892]">{label}</p><p className="mt-5 font-mono text-2xl text-[#dce5e9]">{value}</p></article>)}
      </section>
      <section className="mt-4 grid gap-4 xl:grid-cols-2">
        <article className="rounded-[24px] border border-white/[.07] bg-[#10171c] p-5 sm:p-6"><div className="flex items-start justify-between gap-4"><div><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Current browser session</p><h2 className="mt-1 text-base font-medium">Vehicle evolution</h2></div><span className="font-mono text-[10px] text-[#667781]">{history.length} points</span></div><div className="mt-5"><LineChart points={history} series={vehicleSeries} /></div></article>
        <article className="rounded-[24px] border border-white/[.07] bg-[#10171c] p-5 sm:p-6"><div className="flex items-start justify-between gap-4"><div><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Current browser session</p><h2 className="mt-1 text-base font-medium">Queue evolution by approach</h2></div><span className="font-mono text-[10px] text-[#667781]">SUMO halting number</span></div><div className="mt-5"><LineChart points={history} series={queueSeries} /></div></article>
      </section>
      <div className="mt-4 grid gap-3 sm:grid-cols-3"><div className="rounded-xl border border-white/[.06] bg-[#10171c] px-4 py-3 text-sm"><span className="text-[#73838d]">Simulation state</span><span className="float-right font-mono capitalize">{status.state}</span></div><div className="rounded-xl border border-white/[.06] bg-[#10171c] px-4 py-3 text-sm"><span className="text-[#73838d]">WebSocket</span><span className="float-right font-mono capitalize">{connection}</span></div><div className="rounded-xl border border-white/[.06] bg-[#10171c] px-4 py-3 text-sm"><span className="text-[#73838d]">Run</span><span className="float-right max-w-[60%] truncate font-mono text-xs">{snapshot?.run_id ?? "—"}</span></div></div>
    </div>
  );
}
