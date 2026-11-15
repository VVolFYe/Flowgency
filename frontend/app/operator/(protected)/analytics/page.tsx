"use client";

import { AiReview } from "@/components/analytics/ai-review";
import { ConnectionBadge, formatTime } from "@/components/simulation/simulation-workspace";
import { useSimulation, type HistoryPoint } from "@/components/simulation/simulation-provider";
import { LineChart, type LineSeries } from "@/components/statistics/charts";
import { formatNumber } from "@/components/statistics/format";
import { KpiTile } from "@/components/statistics/section";
import { usePathname } from "next/navigation";
import "@/components/statistics/statistics.css";

const EMPTY_CHART = "Waiting for at least two real snapshots.";

function toSeries(points: HistoryPoint[], label: string, value: (point: HistoryPoint) => number | null): LineSeries {
  return { label, points: points.map((point) => ({ x: point.simulationTimeS, y: value(point) })) };
}

function valueMax(values: Array<number | null>) {
  const known = values.filter((value): value is number => value != null);
  return known.length ? Math.max(...known) : null;
}

function StatusRow({ label, value, capitalize = false, title }: { label: string; value: string; capitalize?: boolean; title?: string }) {
  return (
    <div className="stats-panel flex min-w-0 items-center justify-between gap-4 px-4 py-3 text-sm">
      <span className="shrink-0 text-[#b8a393]">{label}</span>
      <span className={`min-w-0 truncate text-right font-mono text-xs text-[#fff4eb] ${capitalize ? "capitalize" : ""}`} title={title}>{value}</span>
    </div>
  );
}

export default function SessionAnalytics() {
  const workspace = usePathname().startsWith("/analyst") ? "Analyst" : "Operator";
  const { history, status, snapshot, connection } = useSimulation();
  const approaches = Array.from(new Set(history.flatMap((point) => Object.keys(point.queues))));
  const currentVehicles = snapshot?.vehicles ? snapshot.vehicles.length : null;
  const maxVehicles = valueMax(history.map((point) => point.vehicleCount));
  const currentQueues = Object.values(snapshot?.queue_lengths_by_approach ?? {}).map((value) => value?.vehicles ?? null);
  const activeEmergencyVehicles = snapshot?.vehicles?.filter((vehicle) => vehicle.is_emergency).length ?? null;
  const activePriorityRequests = snapshot?.emergency_events?.filter((event) => event.state === "priority_active").length ?? null;
  const historicalQueues = history.flatMap((point) => Object.values(point.queues));
  const queueSeries = approaches.map((approach) => toSeries(history, approach, (point) => point.queues[approach] ?? null));
  const vehicleSeries = [toSeries(history, "Active vehicles", (point) => point.vehicleCount)];
  const kpis: Array<{ label: string; value: string; unit?: string; emphasis?: boolean }> = [
    { label: "Current vehicles", value: formatNumber(currentVehicles, 0), unit: "veh", emphasis: true },
    { label: "Max vehicles", value: formatNumber(maxVehicles, 0), unit: "veh" },
    { label: "Current max queue", value: formatNumber(valueMax(currentQueues), 0), unit: "veh" },
    { label: "Session max queue", value: formatNumber(valueMax(historicalQueues), 0), unit: "veh" },
    { label: "Simulation time", value: formatTime(snapshot?.simulation_time_s ?? status.simulation_time_s) },
    { label: "Emergency vehicles", value: formatNumber(activeEmergencyVehicles, 0), unit: "veh" },
    { label: "Priority requests", value: formatNumber(activePriorityRequests, 0) },
  ];
  return (
    <div className="analytics-page stats-scope">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="eyebrow">{workspace} analytics</p>
          <h1 className="mt-2 text-4xl font-semibold tracking-[-.045em] text-[#fff4eb]">Current browser session</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[#dccdc0]">Real WebSocket snapshots only. The series resets when a new <span className="font-mono text-[#fff4eb]">run_id</span> appears and is not persisted beyond this browser session.</p>
        </div>
        <ConnectionBadge connection={connection} stale={connection !== "connected" && snapshot !== null} />
      </div>

      <section aria-label="Session indicators" className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
        {kpis.map((kpi) => <KpiTile key={kpi.label} label={kpi.label} value={kpi.value} unit={kpi.unit} emphasis={kpi.emphasis} />)}
      </section>

      {status.active_configuration && (
        <div className="stats-panel mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-xs text-[#b8a393]">
          <span className="font-semibold text-[#dccdc0]">Active configuration</span>
          <span className="font-mono text-[#fff4eb]">{status.active_configuration.network} · {status.active_configuration.traffic_profile} · {status.active_configuration.controller_mode} · emergency {status.active_configuration.emergency_vehicles_enabled ? "enabled" : "disabled"}</span>
        </div>
      )}

      <section className="mt-4 grid gap-4 xl:grid-cols-2">
        <article className="stats-card">
          <div className="stats-card-head">
            <div className="min-w-0">
              <p className="stats-group-title">Current browser session</p>
              <h2 className="mt-1.5">Vehicle evolution</h2>
            </div>
            <span className="stats-pill">{history.length} {history.length === 1 ? "point" : "points"}</span>
          </div>
          <div className="stats-card-body">
            <LineChart title="Active vehicles" xLabel="simulation time" yLabel="vehicles" formatX={formatTime} formatY={(y) => formatNumber(y, 0)} series={vehicleSeries} emptyMessage={EMPTY_CHART} />
          </div>
        </article>
        <article className="stats-card">
          <div className="stats-card-head">
            <div className="min-w-0">
              <p className="stats-group-title">Current browser session</p>
              <h2 className="mt-1.5">Queue evolution by approach</h2>
            </div>
            <span className="stats-pill">SUMO halting number</span>
          </div>
          <div className="stats-card-body">
            <LineChart title="Halting vehicles per approach" xLabel="simulation time" yLabel="vehicles" formatX={formatTime} formatY={(y) => formatNumber(y, 0)} series={queueSeries} emptyMessage={EMPTY_CHART} />
          </div>
        </article>
      </section>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <StatusRow label="Simulation state" value={status.state} capitalize />
        <StatusRow label="WebSocket" value={connection} capitalize />
        <StatusRow label="Run" value={snapshot?.run_id ?? "—"} title={snapshot?.run_id ?? undefined} />
      </div>

      <AiReview />
    </div>
  );
}
