"use client";

import { useMemo } from "react";
import { SimulationCanvas } from "@/components/simulation-canvas";
import { BACKEND_URL } from "@/lib/api";
import type { ServiceState } from "@/lib/contracts";
import {
  useSimulation,
  type ConnectionState,
  type ControlMode,
  type SimulationCommand,
} from "./simulation-provider";

const STATE_LABELS: Record<ServiceState, string> = {
  idle: "Ready",
  running: "Live",
  paused: "Paused",
  finished: "Finished",
  error: "Error",
};

const APPROACH_LABELS: Record<string, string> = {
  northbound_in: "Northbound",
  southbound_in: "Southbound",
  eastbound_in: "Eastbound",
  westbound_in: "Westbound",
};

const SPEED_PRESETS = [1, 2, 4, 8, 16, 32] as const;

export function formatTime(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  const remainder = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}

function formatAccumulatedTime(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)} min`;
  return `${(seconds / 3600).toFixed(2)} hr`;
}

export function ConnectionBadge({ connection, stale = false }: { connection: ConnectionState; stale?: boolean }) {
  const label = connection === "offline" ? "Backend disconnected" : connection;
  return (
    <div className="flex items-center gap-3 rounded-full border border-white/10 bg-[#10171b] px-4 py-2 text-xs shadow-lg shadow-black/10">
      <span className={`h-2 w-2 rounded-full ${connection === "connected" ? "bg-[#7cf2ad] shadow-[0_0_10px_rgba(124,242,173,.45)]" : connection === "offline" ? "bg-[#ff727b]" : "pulse-soft bg-[#f1bd59]"}`} />
      <span className="capitalize text-[#a8b5bd]">{label}</span>
      {stale && <span className="border-l border-white/10 pl-3 font-medium text-[#f0bc55]">stale frame</span>}
    </div>
  );
}

function ControlButton({ label, action, enabled, busy, primary, onClick }: {
  label: string; action: string; enabled: boolean; busy: boolean; primary?: boolean; onClick: () => void;
}) {
  return (
    <button type="button" disabled={!enabled || busy} onClick={onClick} className={`group flex min-h-11 items-center justify-between rounded-xl border px-4 text-sm font-medium transition ${primary ? "border-[#70e9a6]/50 bg-[#70e9a6] text-[#06130c] hover:bg-[#8df5bb]" : "border-white/10 bg-white/[.035] text-[#d7e1e6] hover:border-white/20 hover:bg-white/[.065]"} disabled:cursor-not-allowed disabled:opacity-30`}>
      <span>{busy ? "Working…" : label}</span><span className="font-mono text-[10px] uppercase tracking-widest opacity-60">{action}</span>
    </button>
  );
}

function LiveTelemetry({ operator }: { operator: boolean }) {
  const { geometry, selectedScenarioId, status, snapshot } = useSimulation();
  const vehicleCount = snapshot?.vehicles ? snapshot.vehicles.length : null;
  const singleIntersection = selectedScenarioId.startsWith("single_intersection");
  return (
    <div className="surface rounded-[20px] p-4">
      <p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Live telemetry</p>
      <div className="mt-5 grid grid-cols-2 gap-3">
        <div className="rounded-xl border border-white/[.05] bg-[#0b1114] p-3"><p className="text-[11px] text-[#73838d]">Simulation time</p><p className="mt-2 font-mono text-2xl font-medium tracking-tight">{formatTime(snapshot?.simulation_time_s ?? status.simulation_time_s)}</p></div>
        <div className="rounded-xl border border-white/[.05] bg-[#0b1114] p-3"><p className="text-[11px] text-[#73838d]">Vehicles active</p><p className="mt-2 font-mono text-2xl font-medium tracking-tight">{vehicleCount ?? "—"}</p></div>
      </div>
      <div className="mt-4 space-y-2 border-t border-white/[.06] pt-4 text-xs">
        <div className="flex justify-between gap-3"><span className="text-[#73838d]">Simulation state</span><span className="font-mono text-[#c5d0d6]">{STATE_LABELS[status.state]}</span></div>
        {singleIntersection ? <>
          <div className="flex justify-between gap-3"><span className="text-[#73838d]">Phase</span><span className="max-w-[165px] truncate font-mono text-[#c5d0d6]">{snapshot?.current_phase_id || "—"}</span></div>
          <div className="flex justify-between gap-3"><span className="text-[#73838d]">Next switch</span><span className="font-mono text-[#c5d0d6]">{snapshot?.remaining_phase_duration_s == null ? "—" : `${snapshot.remaining_phase_duration_s.toFixed(0)}s`}</span></div>
        </> : <>
          <div className="flex justify-between gap-3"><span className="text-[#73838d]">Controllers</span><span className="font-mono text-[#c5d0d6]">{snapshot?.traffic_light_controllers ? Object.keys(snapshot.traffic_light_controllers).length : geometry?.traffic_lights.length ?? "—"}</span></div>
          <div className="flex justify-between gap-3"><span className="text-[#73838d]">Network queue</span><span className="font-mono text-[#c5d0d6]">{snapshot?.network_queue?.vehicles ?? "—"}</span></div>
        </>}
        {snapshot?.emergency_priority?.active_vehicle_id && <div className="flex justify-between gap-3 text-[#ff9b72]"><span>Emergency priority</span><span className="max-w-[165px] truncate font-mono">{snapshot.emergency_priority.active_vehicle_id}</span></div>}
        {operator && <div className="flex justify-between gap-3"><span className="text-[#73838d]">Run</span><span className="max-w-[165px] truncate font-mono text-[10px] text-[#82939d]" title={snapshot?.run_id}>{snapshot?.run_id ?? "—"}</span></div>}
      </div>
    </div>
  );
}

function Queues() {
  const { geometry, selectedScenarioId, snapshot } = useSimulation();
  const rows = useMemo(() => {
    if (!selectedScenarioId.startsWith("single_intersection")) return [];
    const approaches = geometry ? Array.from(new Set(geometry.controlled_links.map((link) => link.approach))) : Object.keys(APPROACH_LABELS);
    return approaches.map((approach) => ({ approach, value: snapshot?.queue_lengths_by_approach[approach]?.vehicles ?? null }));
  }, [geometry, selectedScenarioId, snapshot]);
  const measured = rows.map((row) => row.value).filter((value): value is number => value != null);
  const maxQueue = measured.length ? Math.max(1, ...measured) : null;
  return (
    <div className="surface rounded-[20px] p-4">
      <div className="flex items-center justify-between"><div><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Queues</p><h2 className="mt-1 text-sm font-medium">Halting vehicles</h2></div><span className="text-[10px] text-[#667781]">SUMO</span></div>
      {rows.length ? <div className="mt-4 space-y-2">{rows.map(({ approach, value }) => (
        <div key={approach} className="rounded-xl bg-white/[.025] px-3 py-2.5">
          <div className="flex items-center justify-between text-xs"><span className="text-[#9aa8b0]">{APPROACH_LABELS[approach] ?? approach}</span><span className="font-mono text-[#dce5e9]">{value ?? "—"}</span></div>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/[.06]">{value != null && maxQueue != null && <div className="h-full rounded-full bg-[#70e9a6] transition-[width] duration-300" style={{ width: `${(value / maxQueue) * 100}%` }} />}</div>
        </div>
      ))}</div> : <div className="mt-4 rounded-xl bg-white/[.025] p-3"><div className="flex items-end justify-between"><span className="text-xs text-[#8797a0]">All controlled lanes</span><span className="font-mono text-2xl text-[#dce5e9]">{snapshot?.network_queue?.vehicles ?? "—"}</span></div><p className="mt-2 text-[10px] leading-relaxed text-[#667781]">Deduplicated halting count across {snapshot?.network_queue?.controlled_lane_count ?? "—"} controlled lanes.</p></div>}
      {!snapshot && <p className="mt-3 text-[11px] leading-relaxed text-[#667781]">No measured queue data yet. Unknown values remain distinct from zero.</p>}
    </div>
  );
}

function RunMetrics() {
  const { selectedControlMode, status, snapshot } = useSimulation();
  const metrics = snapshot?.metrics;
  return (
    <div className="surface rounded-[20px] p-4">
      <div className="flex items-center justify-between"><div><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Run metrics</p><h2 className="mt-1 text-sm font-medium">Cumulative waiting</h2></div><span className="rounded-full border border-white/10 px-2 py-1 font-mono text-[9px] uppercase text-[#9cacb5]">{status.control_mode ?? selectedControlMode}</span></div>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <div className="rounded-xl bg-white/[.025] p-3"><p className="text-[10px] text-[#73838d]">Total vehicle-seconds</p><p className="mt-1 font-mono text-lg text-[#e1eaee]">{metrics ? `${metrics.total_waiting_time_s.toFixed(0)}s` : "—"}</p><p className="mt-1 text-[10px] text-[#71818a]">{formatAccumulatedTime(metrics?.total_waiting_time_s)}</p></div>
        <div className="rounded-xl bg-white/[.025] p-3"><p className="text-[10px] text-[#73838d]">Average / departed</p><p className="mt-1 font-mono text-lg text-[#e1eaee]">{metrics?.average_waiting_time_s == null ? "—" : `${metrics.average_waiting_time_s.toFixed(1)}s`}</p><p className="mt-1 text-[10px] text-[#71818a]">{metrics?.departed_vehicle_count ?? "—"} inserted</p></div>
      </div>
      <div className="mt-3 space-y-2 border-t border-white/[.06] pt-3 text-xs">
        <div className="flex justify-between"><span className="text-[#73838d]">Arrived vehicles</span><span className="font-mono text-[#c5d0d6]">{metrics?.arrived_vehicle_count ?? "—"}</span></div>
        <div className="flex justify-between"><span className="text-[#73838d]">Current queue</span><span className="font-mono text-[#c5d0d6]">{metrics?.network_queue_vehicles ?? "—"}</span></div>
        <div className="flex justify-between"><span className="text-[#73838d]">Maximum queue</span><span className="font-mono text-[#c5d0d6]">{metrics?.maximum_network_queue_vehicles ?? "—"}</span></div>
      </div>
    </div>
  );
}

function SnapshotDetails() {
  const { snapshot } = useSimulation();
  const fields = [
    ["Schema version", snapshot?.schema_version], ["Scenario", snapshot?.scenario_selection_id ?? snapshot?.scenario_id],
    ["Run", snapshot?.run_id], ["Intersection", snapshot?.intersection_id], ["Simulation time (s)", snapshot?.simulation_time_s],
    ["Traffic light", snapshot?.traffic_light_id], ["Phase index", snapshot?.current_phase_index], ["Phase ID", snapshot?.current_phase_id],
    ["Remaining phase (s)", snapshot?.remaining_phase_duration_s], ["Signal state", snapshot?.traffic_light_state], ["Coordinate system", snapshot?.coordinate_system],
  ];
  return (
    <details className="surface rounded-[20px] p-4 open:border-white/[.12]">
      <summary className="cursor-pointer text-sm font-medium text-[#cbd6db]">Raw snapshot details</summary>
      <p className="mt-2 text-[11px] leading-5 text-[#667781]">Every value below comes directly from the latest backend snapshot.</p>
      <dl className="mt-4 space-y-2">{fields.map(([label, value]) => <div key={String(label)} className="flex justify-between gap-3 text-xs"><dt className="text-[#73838d]">{label}</dt><dd className="max-w-[60%] truncate font-mono text-[#c5d0d6]" title={value == null ? undefined : String(value)}>{value ?? "—"}</dd></div>)}</dl>
    </details>
  );
}

function OperatorControls() {
  const {
    geometry, scenarios, selectedScenarioId, selectedScenario, selectedSpeed, selectedControlMode,
    status, commandPending, loading, execute, changeScenario, changeSpeed, setSelectedControlMode,
  } = useSimulation();
  const statusTone = status.state === "running" ? "#70e9a6" : status.state === "error" ? "#ff6c76" : "#f0bc55";
  const run = (command: SimulationCommand) => { void execute(command); };
  return (
    <aside className="surface order-2 rounded-[20px] p-4 xl:order-1">
      <div className="mb-5 flex items-center justify-between"><div><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Simulation</p><h2 className="mt-1 text-base font-medium">Run controls</h2></div><div className="rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider" style={{ color: statusTone, borderColor: `${statusTone}40`, background: `${statusTone}10` }}>{STATE_LABELS[status.state]}</div></div>
      <label htmlFor="scenario" className="text-xs text-[#6f808a]">Scenario</label>
      <select id="scenario" value={selectedScenarioId} disabled={status.state !== "idle" || commandPending !== null || loading} onChange={(event) => void changeScenario(event.target.value)} className="mt-2 w-full rounded-xl border border-white/10 bg-[#0b1115] px-3 py-2.5 text-sm text-[#d7e1e6] outline-none focus:border-[#70e9a6]/50 disabled:opacity-50">
        {scenarios.map((scenario) => <option key={scenario.scenario_id} value={scenario.scenario_id}>{scenario.display_name}</option>)}
      </select>
      {selectedScenario && <p className="mt-2 text-[10px] leading-relaxed text-[#70818b]">{selectedScenario.description}</p>}
      {selectedScenario?.known_limitation && <p className="mt-2 rounded-lg border border-[#f0bc55]/20 bg-[#f0bc55]/10 px-2.5 py-2 text-[10px] leading-relaxed text-[#e5c783]">{selectedScenario.known_limitation}</p>}
      <label htmlFor="control-mode" className="mt-4 block text-xs text-[#6f808a]">Control mode</label>
      <select id="control-mode" value={selectedControlMode} disabled={status.state !== "idle" || commandPending !== null} onChange={(event) => setSelectedControlMode(event.target.value as ControlMode)} className="mt-2 w-full rounded-xl border border-white/10 bg-[#0b1115] px-3 py-2.5 text-sm text-[#d7e1e6] outline-none focus:border-[#70e9a6]/50 disabled:opacity-50">
        <option value="fixed">Fixed timing</option>
        <option value="adaptive" disabled={!selectedScenario?.supports_adaptive_control}>Adaptive{selectedScenarioId.startsWith("london_") ? " — J3 only" : ""}</option>
        {selectedScenario?.supports_emergency_priority && <option value="adaptive_with_emergency_priority">Adaptive + emergency priority</option>}
      </select>
      {selectedControlMode === "adaptive" && selectedScenarioId.startsWith("london_") && <p className="mt-2 text-[10px] leading-relaxed text-[#e5c783]">Experimental J3-only control. Imported yellow phases remain fixed; pedestrian and real-world clearance safety are not verified.</p>}
      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
        <ControlButton label="Start simulation" action="Start" primary enabled={status.state === "idle" && geometry !== null} busy={commandPending !== null} onClick={() => run("start")} />
        <ControlButton label="Pause" action="Pause" enabled={status.state === "running"} busy={commandPending !== null} onClick={() => run("pause")} />
        <ControlButton label="Resume" action="Play" enabled={status.state === "paused"} busy={commandPending !== null} onClick={() => run("resume")} />
        <ControlButton label="New run at 00:00" action="Reset" enabled={status.state !== "idle"} busy={commandPending !== null} onClick={() => run("reset")} />
        <ControlButton label="Stop & clear" action="Stop" enabled={status.state !== "idle"} busy={commandPending !== null} onClick={() => run("stop")} />
      </div>
      <div className="mt-4 border-t border-white/[.06] pt-4"><div className="flex items-center justify-between"><span className="text-xs text-[#6f808a]">Simulation speed</span><span className="font-mono text-xs text-[#c7d2d8]">{status.simulation_speed.toFixed(1)}×</span></div><div className="mt-2 grid grid-cols-3 gap-1.5" role="group" aria-label="Simulation speed">{SPEED_PRESETS.map((speed) => <button key={speed} type="button" disabled={commandPending !== null || status.state === "finished" || status.state === "error"} aria-pressed={selectedSpeed === speed} onClick={() => void changeSpeed(speed)} className={`rounded-lg border px-2 py-2 font-mono text-xs transition ${selectedSpeed === speed ? "border-[#70e9a6]/60 bg-[#70e9a6]/15 text-[#8df5bb]" : "border-white/[.08] bg-white/[.025] text-[#91a0a8] hover:border-white/20"} disabled:opacity-35`}>{speed}×</button>)}</div></div>
    </aside>
  );
}

export function SimulationWorkspace({ access }: { access: "public" | "operator" }) {
  const { geometry, selectedScenario, selectedScenarioId, status, snapshot, connection, loading, error, dismissError } = useSimulation();
  const operator = access === "operator";
  const stale = connection !== "connected" && snapshot !== null;
  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4"><div><p className="eyebrow">{operator ? "Operator workspace" : "Public live view"}</p><h1 className="mt-2 text-3xl font-semibold tracking-[-.04em]">Live Simulation</h1>{operator ? <p className="mt-2 text-xs text-[#6f808a]">Authoritative SUMO simulation · {BACKEND_URL}</p> : selectedScenario && <p className="mt-2 max-w-2xl text-xs leading-5 text-[#71818a]">{selectedScenario.display_name} · {selectedScenario.description}</p>}</div><ConnectionBadge connection={connection} stale={stale} /></div>
      {error && <div role="alert" className="mb-4 flex items-start justify-between gap-4 rounded-xl border border-[#ff6670]/25 bg-[#ff6670]/10 px-4 py-3 text-sm text-[#ffabb1]"><span>{error}</span><button type="button" onClick={dismissError} className="text-xs uppercase tracking-wider text-[#ffccd0]">Dismiss</button></div>}
      <section className={`grid gap-4 ${operator ? "xl:grid-cols-[260px_minmax(0,1fr)_285px]" : "lg:grid-cols-[minmax(0,1fr)_285px]"}`}>
        {operator && <OperatorControls />}
        <div className={`surface order-1 min-h-[480px] rounded-[24px] p-2 shadow-2xl shadow-black/30 ${operator ? "xl:order-2 xl:h-[calc(100vh-176px)] xl:min-h-[620px]" : "lg:h-[calc(100vh-180px)] lg:min-h-[600px]"}`}>
          {geometry ? <SimulationCanvas key={geometry.scenario_selection_id ?? selectedScenarioId} geometry={geometry} scenario={selectedScenario} snapshot={snapshot} status={status} connection={connection} /> : <div className="grid h-full min-h-[470px] place-items-center rounded-[20px] bg-[#0b1115] px-6 text-center text-sm text-[#81909a]">{loading ? "Loading SUMO network geometry…" : "Network geometry unavailable while the backend is disconnected."}</div>}
        </div>
        <aside className="order-3 grid content-start gap-4 sm:grid-cols-2 lg:grid-cols-1"><LiveTelemetry operator={operator} />{operator ? <><Queues /><RunMetrics /><SnapshotDetails /></> : <><RunMetrics /><div className="surface rounded-[20px] p-4"><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">About this view</p><p className="mt-3 text-sm leading-6 text-[#8b9aa3]">This read-only feed shows geometry, vehicles and signals produced by the server-owned SUMO simulation. Public viewers cannot change the run.</p></div></>}</aside>
      </section>
    </div>
  );
}
