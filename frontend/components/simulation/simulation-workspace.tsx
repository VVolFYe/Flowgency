"use client";

import { useMemo } from "react";
import { BACKEND_URL } from "@/lib/api";
import type { ServiceState } from "@/lib/contracts";
import { IntersectionCanvas } from "./intersection-canvas";
import { useSimulation, type ConnectionState, type SimulationCommand } from "./simulation-provider";

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

export function formatTime(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  const remainder = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}

export function ConnectionBadge({ connection, stale = false }: { connection: ConnectionState; stale?: boolean }) {
  const label = connection === "offline" ? "Backend disconnected" : connection;
  return (
    <div className="flex items-center gap-3 rounded-full border border-white/10 bg-white/[.025] px-4 py-2 text-xs">
      <span className={`h-2 w-2 rounded-full ${connection === "connected" ? "bg-[#70e9a6]" : connection === "offline" ? "bg-[#ff6c76]" : "pulse-soft bg-[#f0bc55]"}`} />
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
  const { status, snapshot } = useSimulation();
  const vehicleCount = snapshot?.vehicles ? snapshot.vehicles.length : null;
  return (
    <div className="rounded-[20px] border border-white/[.07] bg-[#10171c] p-4">
      <p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Live telemetry</p>
      <div className="mt-5 grid grid-cols-2 gap-3">
        <div className="rounded-xl bg-white/[.025] p-3"><p className="text-[11px] text-[#73838d]">Simulation time</p><p className="mt-2 font-mono text-2xl font-medium tracking-tight">{formatTime(snapshot?.simulation_time_s ?? status.simulation_time_s)}</p></div>
        <div className="rounded-xl bg-white/[.025] p-3"><p className="text-[11px] text-[#73838d]">Vehicles active</p><p className="mt-2 font-mono text-2xl font-medium tracking-tight">{vehicleCount ?? "—"}</p></div>
      </div>
      <div className="mt-4 space-y-2 border-t border-white/[.06] pt-4 text-xs">
        <div className="flex justify-between gap-3"><span className="text-[#73838d]">Simulation state</span><span className="font-mono text-[#c5d0d6]">{STATE_LABELS[status.state]}</span></div>
        {operator && <>
          <div className="flex justify-between gap-3"><span className="text-[#73838d]">Phase</span><span className="max-w-[165px] truncate font-mono text-[#c5d0d6]">{snapshot?.current_phase_id || "—"}</span></div>
          <div className="flex justify-between gap-3"><span className="text-[#73838d]">Next switch</span><span className="font-mono text-[#c5d0d6]">{snapshot?.remaining_phase_duration_s == null ? "—" : `${snapshot.remaining_phase_duration_s.toFixed(0)}s`}</span></div>
          <div className="flex justify-between gap-3"><span className="text-[#73838d]">Signal state</span><span className="max-w-[165px] truncate font-mono text-[#c5d0d6]">{snapshot?.traffic_light_state ?? "—"}</span></div>
          <div className="flex justify-between gap-3"><span className="text-[#73838d]">Run</span><span className="max-w-[165px] truncate font-mono text-[10px] text-[#82939d]" title={snapshot?.run_id}>{snapshot?.run_id ?? "—"}</span></div>
          <div className="flex justify-between gap-3"><span className="text-[#73838d]">Intersection</span><span className="font-mono text-[#82939d]">{snapshot?.intersection_id ?? "—"}</span></div>
        </>}
      </div>
    </div>
  );
}

function Queues() {
  const { geometry, snapshot } = useSimulation();
  const rows = useMemo(() => {
    const approaches = geometry ? Array.from(new Set(geometry.controlled_links.map((link) => link.approach))) : Object.keys(APPROACH_LABELS);
    return approaches.map((approach) => ({ approach, value: snapshot?.queue_lengths_by_approach[approach]?.vehicles ?? null }));
  }, [geometry, snapshot]);
  const measured = rows.map((row) => row.value).filter((value): value is number => value != null);
  const maxQueue = measured.length ? Math.max(1, ...measured) : null;
  return (
    <div className="rounded-[20px] border border-white/[.07] bg-[#10171c] p-4">
      <div className="flex items-center justify-between"><div><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Queues</p><h2 className="mt-1 text-sm font-medium">Halting vehicles</h2></div><span className="text-[10px] text-[#667781]">SUMO</span></div>
      <div className="mt-4 space-y-2">{rows.map(({ approach, value }) => (
        <div key={approach} className="rounded-xl bg-white/[.025] px-3 py-2.5">
          <div className="flex items-center justify-between text-xs"><span className="text-[#9aa8b0]">{APPROACH_LABELS[approach] ?? approach}</span><span className="font-mono text-[#dce5e9]">{value ?? "—"}</span></div>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/[.06]">{value != null && maxQueue != null && <div className="h-full rounded-full bg-[#70e9a6] transition-[width] duration-300" style={{ width: `${(value / maxQueue) * 100}%` }} />}</div>
        </div>
      ))}</div>
      {!snapshot && <p className="mt-3 text-[11px] leading-relaxed text-[#667781]">No measured queue data yet. Unknown values remain distinct from zero.</p>}
    </div>
  );
}

function SnapshotDetails() {
  const { snapshot } = useSimulation();
  const fields = [
    ["Schema version", snapshot?.schema_version],
    ["Scenario", snapshot?.scenario_id],
    ["Run", snapshot?.run_id],
    ["Intersection", snapshot?.intersection_id],
    ["Simulation time (s)", snapshot?.simulation_time_s],
    ["Traffic light", snapshot?.traffic_light_id],
    ["Phase index", snapshot?.current_phase_index],
    ["Phase ID", snapshot?.current_phase_id],
    ["Remaining phase (s)", snapshot?.remaining_phase_duration_s],
    ["Signal state", snapshot?.traffic_light_state],
    ["Coordinate system", snapshot?.coordinate_system],
  ];
  return (
    <details className="rounded-[20px] border border-white/[.07] bg-[#10171c] p-4">
      <summary className="cursor-pointer text-sm font-medium text-[#cbd6db]">Raw snapshot details</summary>
      <p className="mt-2 text-[11px] leading-5 text-[#667781]">Every value below comes directly from the latest backend snapshot.</p>
      <dl className="mt-4 space-y-2">{fields.map(([label, value]) => <div key={String(label)} className="flex justify-between gap-3 text-xs"><dt className="text-[#73838d]">{label}</dt><dd className="max-w-[60%] truncate font-mono text-[#c5d0d6]" title={value == null ? undefined : String(value)}>{value ?? "—"}</dd></div>)}</dl>
      <div className="mt-4 border-t border-white/[.06] pt-4"><p className="font-mono text-[10px] uppercase tracking-[.18em] text-[#667781]">Vehicles · {snapshot?.vehicles?.length ?? "—"}</p>
        {snapshot?.vehicles ? <div className="mt-3 max-h-64 space-y-2 overflow-auto pr-1">{snapshot.vehicles.map((vehicle) => <div key={vehicle.vehicle_id} className="rounded-lg bg-white/[.025] p-2 font-mono text-[10px] leading-5 text-[#8fa0a9]"><div className="truncate text-[#d3dde2]">{vehicle.vehicle_id} · {vehicle.vehicle_type}</div><div>x {vehicle.x_m} · y {vehicle.y_m} · {vehicle.angle_deg}°</div><div>{vehicle.speed_mps} m/s · {vehicle.road_id}</div></div>)}</div> : <p className="mt-2 text-[11px] text-[#667781]">—</p>}
      </div>
    </details>
  );
}

export function SimulationWorkspace({ access }: { access: "public" | "operator" }) {
  const { geometry, status, snapshot, connection, loading, commandPending, error, transitionRef, execute, dismissError } = useSimulation();
  const operator = access === "operator";
  const stale = connection !== "connected" && snapshot !== null;
  const statusTone = status.state === "running" ? "#70e9a6" : status.state === "error" ? "#ff6c76" : "#f0bc55";
  const run = (command: SimulationCommand) => { void execute(command); };

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#72e9a6]">{operator ? "Operator workspace" : "Public live view"}</p><h1 className="mt-1 text-2xl font-semibold tracking-tight">Live Simulation</h1>{operator && <p className="mt-1 text-xs text-[#6f808a]">Authoritative SUMO simulation · {BACKEND_URL}</p>}</div>
        <ConnectionBadge connection={connection} stale={stale} />
      </div>
      {error && <div role="alert" className="mb-4 flex items-start justify-between gap-4 rounded-xl border border-[#ff6670]/25 bg-[#ff6670]/10 px-4 py-3 text-sm text-[#ffabb1]"><span>{error}</span><button type="button" onClick={dismissError} className="text-xs uppercase tracking-wider text-[#ffccd0]">Dismiss</button></div>}

      <section className={`grid gap-4 ${operator ? "xl:grid-cols-[260px_minmax(0,1fr)_285px]" : "lg:grid-cols-[minmax(0,1fr)_285px]"}`}>
        {operator && <aside className="order-2 rounded-[20px] border border-white/[.07] bg-[#10171c] p-4 xl:order-1">
          <div className="mb-5 flex items-center justify-between"><div><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Simulation</p><h2 className="mt-1 text-base font-medium">Run controls</h2></div><div className="rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider" style={{ color: statusTone, borderColor: `${statusTone}40`, background: `${statusTone}10` }}>{STATE_LABELS[status.state]}</div></div>
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
            <ControlButton label="Start simulation" action="Start" primary enabled={status.state === "idle"} busy={commandPending !== null} onClick={() => run("start")} />
            <ControlButton label="Pause" action="Pause" enabled={status.state === "running"} busy={commandPending !== null} onClick={() => run("pause")} />
            <ControlButton label="Resume" action="Play" enabled={status.state === "paused"} busy={commandPending !== null} onClick={() => run("resume")} />
            <ControlButton label="New run at 00:00" action="Reset" enabled={status.state !== "idle"} busy={commandPending !== null} onClick={() => run("reset")} />
            <ControlButton label="Stop & clear" action="Stop" enabled={status.state !== "idle"} busy={commandPending !== null} onClick={() => run("stop")} />
          </div>
          <div className="mt-5 rounded-xl border border-white/[.06] bg-black/10 p-3 text-xs leading-relaxed text-[#7f909b]">Reset starts a fresh SUMO run at zero and keeps it paused. Stop returns the service to idle and clears the frame.</div>
          <div className="mt-4 flex items-center justify-between border-t border-white/[.06] pt-4 text-xs"><span className="text-[#6f808a]">Simulation speed</span><span className="font-mono text-[#c7d2d8]">{status.simulation_speed.toFixed(1)}×</span></div>
        </aside>}

        <div className={`order-1 min-h-[480px] rounded-[24px] border border-white/[.08] bg-[#10171c] p-2 shadow-2xl shadow-black/30 ${operator ? "xl:order-2 xl:h-[calc(100vh-176px)] xl:min-h-[620px]" : "lg:h-[calc(100vh-180px)] lg:min-h-[600px]"}`}>
          {geometry ? <IntersectionCanvas geometry={geometry} snapshot={snapshot} status={status} connection={connection} transitionRef={transitionRef} /> : <div className="grid h-full min-h-[470px] place-items-center rounded-[20px] bg-[#0b1115] px-6 text-center text-sm text-[#81909a]">{loading ? "Loading SUMO network geometry…" : "Network geometry unavailable while the backend is disconnected."}</div>}
        </div>

        <aside className="order-3 grid content-start gap-4 sm:grid-cols-2 lg:grid-cols-1"><LiveTelemetry operator={operator} />{operator ? <><Queues /><SnapshotDetails /></> : <div className="rounded-[20px] border border-white/[.07] bg-[#10171c] p-4"><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">About this view</p><p className="mt-3 text-sm leading-6 text-[#8b9aa3]">This read-only feed shows geometry, vehicles and signals produced by the server-owned SUMO simulation. Public viewers cannot change the run.</p></div>}</aside>
      </section>
    </div>
  );
}
