"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, BACKEND_URL, WS_URL } from "@/lib/api";
import { SiteNav } from "@/components/site-nav";
import { SimulationCanvas } from "@/components/simulation-canvas";
import type {
  NetworkGeometry,
  ServiceState,
  SimulationScenario,
  SimulationSnapshot,
  SimulationStatus,
  StreamEnvelope,
} from "@/lib/contracts";

type ConnectionState = "connecting" | "connected" | "reconnecting" | "offline";

const EMPTY_STATUS: SimulationStatus = {
  state: "idle",
  simulation_speed: 4,
  control_mode: "fixed",
  scenario_id: "single_intersection",
  simulation_time_s: null,
  has_snapshot: false,
  error: null,
};

const SPEED_PRESETS = [1, 2, 4, 8, 16, 32] as const;

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

function formatTime(seconds: number | null | undefined) {
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


function ControlButton({ label, action, enabled, busy, primary, onClick }: {
  label: string;
  action: string;
  enabled: boolean;
  busy: boolean;
  primary?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={!enabled || busy}
      onClick={onClick}
      className={`group flex min-h-11 items-center justify-between rounded-xl border px-4 text-sm font-medium transition ${
        primary
          ? "border-[#70e9a6]/50 bg-[#70e9a6] text-[#06130c] hover:bg-[#8df5bb]"
          : "border-white/10 bg-white/[.035] text-[#d7e1e6] hover:border-white/20 hover:bg-white/[.065]"
      } disabled:cursor-not-allowed disabled:opacity-30`}
    >
      <span>{busy ? "Working…" : label}</span>
      <span className="font-mono text-[10px] uppercase tracking-widest opacity-60">{action}</span>
    </button>
  );
}

export default function SimulationPage() {
  const [geometry, setGeometry] = useState<NetworkGeometry | null>(null);
  const [scenarios, setScenarios] = useState<SimulationScenario[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState("single_intersection");
  const [status, setStatus] = useState<SimulationStatus>(EMPTY_STATUS);
  const [snapshot, setSnapshot] = useState<SimulationSnapshot | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [loading, setLoading] = useState(true);
  const [commandPending, setCommandPending] = useState<string | null>(null);
  const [selectedSpeed, setSelectedSpeed] = useState(4);
  const [selectedControlMode, setSelectedControlMode] = useState<"fixed" | "adaptive" | "adaptive_with_emergency_priority">("fixed");
  const [error, setError] = useState<string | null>(null);
  const snapshotRef = useRef<SimulationSnapshot | null>(null);
  const connectionRef = useRef<ConnectionState>("connecting");
  const statusRef = useRef<SimulationStatus>(EMPTY_STATUS);
  const selectedScenarioRef = useRef("single_intersection");
  const geometryRequestRef = useRef(0);

  const loadGeometry = useCallback(async (scenarioId: string) => {
    const requestId = ++geometryRequestRef.current;
    setLoading(true);
    setGeometry(null);
    try {
      const network = await api.network(scenarioId);
      if (requestId === geometryRequestRef.current) setGeometry(network);
    } catch (reason) {
      if (requestId === geometryRequestRef.current) {
        setError(reason instanceof Error ? reason.message : "Failed to load network geometry");
      }
    } finally {
      if (requestId === geometryRequestRef.current) setLoading(false);
    }
  }, []);

  const updateStatus = useCallback((next: SimulationStatus) => {
    statusRef.current = next;
    setStatus(next);
    if (next.state !== "idle" && next.control_mode) setSelectedControlMode(next.control_mode);
    if (!next.has_snapshot || next.state === "idle") {
      snapshotRef.current = null;
      setSnapshot(null);
    }
    if (next.error) setError(next.error);
  }, []);

  const receiveSnapshot = useCallback((next: SimulationSnapshot) => {
    const previous = snapshotRef.current;
    const nextScenario = next.scenario_selection_id ?? next.scenario_id;
    const previousScenario = previous?.scenario_selection_id ?? previous?.scenario_id;
    if (statusRef.current.state !== "idle" && nextScenario !== statusRef.current.scenario_id) return;
    if (
      previous
      && previous.run_id === next.run_id
      && previousScenario === nextScenario
      && next.simulation_time_s <= previous.simulation_time_s
    ) return;
    snapshotRef.current = next;
    setSnapshot(next);
  }, []);

  const refreshHttp = useCallback(async (includeSnapshot = false) => {
    const nextStatus = await api.status();
    updateStatus(nextStatus);
    if (includeSnapshot || nextStatus.has_snapshot) {
      const latest = await api.snapshot();
      if (latest) receiveSnapshot(latest);
    }
  }, [receiveSnapshot, updateStatus]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.scenarios(), api.status()])
      .then(async ([availableScenarios, initialStatus]) => {
        if (cancelled) return;
        const scenarioId = initialStatus.scenario_id || "single_intersection";
        setScenarios(availableScenarios);
        setSelectedScenarioId(scenarioId);
        selectedScenarioRef.current = scenarioId;
        updateStatus(initialStatus);
        setSelectedSpeed(initialStatus.simulation_speed);
        setSelectedControlMode(initialStatus.control_mode ?? "fixed");
        const [network, initialSnapshot] = await Promise.all([
          api.network(scenarioId),
          initialStatus.has_snapshot ? api.snapshot() : Promise.resolve(null),
        ]);
        if (cancelled) return;
        setGeometry(network);
        if (initialSnapshot) receiveSnapshot(initialSnapshot);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Failed to load simulation");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [receiveSnapshot, updateStatus]);

  useEffect(() => {
    if (status.state === "idle" || status.scenario_id === selectedScenarioRef.current) return;
    selectedScenarioRef.current = status.scenario_id;
    setSelectedScenarioId(status.scenario_id);
    snapshotRef.current = null;
    setSnapshot(null);
    void loadGeometry(status.scenario_id);
  }, [loadGeometry, status.scenario_id, status.state]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;
    let attempt = 0;

    const setConnectionState = (next: ConnectionState) => {
      connectionRef.current = next;
      setConnection(next);
    };
    const connect = () => {
      if (closed) return;
      setConnectionState(attempt === 0 ? "connecting" : "reconnecting");
      socket = new WebSocket(WS_URL);
      socket.onopen = () => {
        attempt = 0;
        setConnectionState("connected");
        void refreshHttp(true).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Sync failed"));
      };
      socket.onmessage = (event) => {
        try {
          const envelope = JSON.parse(String(event.data)) as StreamEnvelope;
          if (envelope.type === "snapshot") receiveSnapshot(envelope.data);
          else if (envelope.type === "status") updateStatus(envelope.data);
        } catch {
          setError("The backend sent an invalid WebSocket message");
        }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (closed) return;
        attempt += 1;
        setConnectionState(attempt >= 4 ? "offline" : "reconnecting");
        const delay = Math.min(10000, 500 * 2 ** Math.min(attempt, 5));
        reconnectTimer = setTimeout(connect, delay);
      };
    };
    connect();
    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [receiveSnapshot, refreshHttp, updateStatus]);

  useEffect(() => {
    const timer = setInterval(() => {
      void refreshHttp(false).catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Backend status check failed");
      });
    }, 2500);
    return () => clearInterval(timer);
  }, [refreshHttp]);

  const execute = async (command: "start" | "pause" | "resume" | "reset" | "stop") => {
    setCommandPending(command);
    setError(null);
    try {
      const nextStatus = await api.command(
        command,
        command === "start" || command === "resume" ? selectedSpeed : undefined,
        command === "start" ? selectedScenarioRef.current : undefined,
        command === "start" ? selectedControlMode : undefined,
      );
      updateStatus(nextStatus);
      setSelectedSpeed(nextStatus.simulation_speed);
      setSelectedControlMode(nextStatus.control_mode ?? "fixed");
      if (command === "stop") {
        snapshotRef.current = null;
        setSnapshot(null);
        selectedScenarioRef.current = nextStatus.scenario_id;
        setSelectedScenarioId(nextStatus.scenario_id);
        await loadGeometry(nextStatus.scenario_id);
      } else {
        const latest = await api.snapshot();
        if (latest) receiveSnapshot(latest);
      }
      await refreshHttp(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `Could not ${command} simulation`);
      try {
        await refreshHttp(true);
        setSelectedSpeed(statusRef.current.simulation_speed);
      } catch { /* retain command error */ }
    } finally {
      setCommandPending(null);
    }
  };

  const changeSpeed = async (speed: number) => {
    setSelectedSpeed(speed);
    if (statusRef.current.state === "idle") return;
    setCommandPending("speed");
    setError(null);
    try {
      const nextStatus = await api.setSpeed(speed);
      updateStatus(nextStatus);
      setSelectedSpeed(nextStatus.simulation_speed);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not change simulation speed");
      try {
        await refreshHttp(true);
        setSelectedSpeed(statusRef.current.simulation_speed);
      } catch { /* retain command error */ }
    } finally {
      setCommandPending(null);
    }
  };

  const changeScenario = async (scenarioId: string) => {
    if (statusRef.current.state !== "idle" || commandPending) return;
    selectedScenarioRef.current = scenarioId;
    setSelectedScenarioId(scenarioId);
    const nextScenario = scenarios.find((scenario) => scenario.scenario_id === scenarioId);
    setSelectedControlMode(nextScenario?.default_control_mode ?? "fixed");
    snapshotRef.current = null;
    setSnapshot(null);
    setError(null);
    await loadGeometry(scenarioId);
  };

  const queueRows = useMemo(() => {
    if (!selectedScenarioId.startsWith("single_intersection")) return [];
    const known = snapshot?.queue_lengths_by_approach;
    const approaches = geometry
      ? Array.from(new Set(geometry.controlled_links.map((link) => link.approach)))
      : Object.keys(APPROACH_LABELS);
    return approaches.map((approach) => ({ approach, value: known?.[approach]?.vehicles ?? null }));
  }, [geometry, selectedScenarioId, snapshot]);

  const selectedScenario = scenarios.find((scenario) => scenario.scenario_id === selectedScenarioId) ?? null;
  const metrics = snapshot?.metrics;
  const isStale = connection !== "connected" && snapshot !== null;
  const vehicleCount = snapshot?.vehicles ? snapshot.vehicles.length : null;
  const statusTone = status.state === "running" ? "#70e9a6" : status.state === "error" ? "#ff6c76" : "#f0bc55";

  return (
    <main className="min-h-screen bg-[#080c0f] px-3 py-3 text-[#e8eef4] sm:px-5 sm:py-5">
      <div className="mx-auto max-w-[1600px]">
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3 px-1">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl border border-[#72e9a6]/25 bg-[#72e9a6]/10 text-[#72e9a6]">
              <span className="text-xl">⌁</span>
            </div>
            <div>
              <div className="flex items-baseline gap-2">
                <h1 className="text-lg font-semibold tracking-tight">Flowgency</h1>
                <span className="font-mono text-[9px] uppercase tracking-[.2em] text-[#6d7d87]">Control center</span>
              </div>
              <p className="text-xs text-[#7f909b]">Authoritative SUMO simulation · {BACKEND_URL}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <SiteNav active="simulation" />
            <div className="flex items-center gap-3 rounded-full border border-white/10 bg-white/[.025] px-4 py-2 text-xs">
              <span className={`h-2 w-2 rounded-full ${connection === "connected" ? "bg-[#70e9a6]" : "pulse-soft bg-[#f0bc55]"}`} />
              <span className="capitalize text-[#a8b5bd]">{connection}</span>
              {isStale && <span className="border-l border-white/10 pl-3 font-medium text-[#f0bc55]">stale frame</span>}
            </div>
          </div>
        </header>

        {error && (
          <div role="alert" className="mb-4 flex items-start justify-between gap-4 rounded-xl border border-[#ff6670]/25 bg-[#ff6670]/10 px-4 py-3 text-sm text-[#ffabb1]">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="text-xs uppercase tracking-wider text-[#ffccd0]">Dismiss</button>
          </div>
        )}

        <section className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)_285px]">
          <aside className="order-2 rounded-[20px] border border-white/[.07] bg-[#10171c] p-4 xl:order-1">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Simulation</p>
                <h2 className="mt-1 text-base font-medium">Run controls</h2>
              </div>
              <div className="rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider" style={{ color: statusTone, borderColor: `${statusTone}40`, background: `${statusTone}10` }}>
                {STATE_LABELS[status.state]}
              </div>
            </div>
            <div className="mb-4">
              <label htmlFor="scenario" className="text-xs text-[#6f808a]">Scenario</label>
              <select
                id="scenario"
                value={selectedScenarioId}
                disabled={status.state !== "idle" || commandPending !== null || loading}
                onChange={(event) => void changeScenario(event.target.value)}
                className="mt-2 w-full rounded-xl border border-white/10 bg-[#0b1115] px-3 py-2.5 text-sm text-[#d7e1e6] outline-none transition focus:border-[#70e9a6]/50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {scenarios.map((scenario) => (
                  <option key={scenario.scenario_id} value={scenario.scenario_id}>{scenario.display_name}</option>
                ))}
              </select>
              {selectedScenario && <p className="mt-2 text-[10px] leading-relaxed text-[#70818b]">{selectedScenario.description}</p>}
              {selectedScenario?.known_limitation && (
                <p className="mt-2 rounded-lg border border-[#f0bc55]/20 bg-[#f0bc55]/10 px-2.5 py-2 text-[10px] leading-relaxed text-[#e5c783]">
                  {selectedScenario.known_limitation}
                </p>
              )}
            </div>
            <div className="mb-4">
              <label htmlFor="control-mode" className="text-xs text-[#6f808a]">Control mode</label>
              <select
                id="control-mode"
                value={selectedControlMode}
                disabled={status.state !== "idle" || commandPending !== null}
                onChange={(event) => setSelectedControlMode(event.target.value as "fixed" | "adaptive" | "adaptive_with_emergency_priority")}
                className="mt-2 w-full rounded-xl border border-white/10 bg-[#0b1115] px-3 py-2.5 text-sm text-[#d7e1e6] outline-none transition focus:border-[#70e9a6]/50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <option value="fixed">Fixed timing</option>
                <option value="adaptive" disabled={!selectedScenario?.supports_adaptive_control}>Adaptive{selectedScenarioId.startsWith("london_") ? " — J3 only" : ""}</option>
                {selectedScenario?.supports_emergency_priority && <option value="adaptive_with_emergency_priority">Adaptive + emergency priority</option>}
              </select>
              {selectedControlMode === "adaptive" && selectedScenarioId.startsWith("london_") && (
                <p className="mt-2 text-[10px] leading-relaxed text-[#e5c783]">Experimental J3-only control. Imported yellow phases remain fixed; pedestrian and real-world clearance safety are not verified.</p>
              )}
            </div>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
              <ControlButton label="Start simulation" action="Start" primary enabled={status.state === "idle" && geometry !== null} busy={commandPending !== null} onClick={() => execute("start")} />
              <ControlButton label="Pause" action="Pause" enabled={status.state === "running"} busy={commandPending !== null} onClick={() => execute("pause")} />
              <ControlButton label="Resume" action="Play" enabled={status.state === "paused"} busy={commandPending !== null} onClick={() => execute("resume")} />
              <ControlButton label="New run at 00:00" action="Reset" enabled={status.state !== "idle"} busy={commandPending !== null} onClick={() => execute("reset")} />
              <ControlButton label="Stop & clear" action="Stop" enabled={status.state !== "idle"} busy={commandPending !== null} onClick={() => execute("stop")} />
            </div>
            <div className="mt-4 border-t border-white/[.06] pt-4">
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#6f808a]">Simulation speed</span>
                <span className="font-mono text-xs text-[#c7d2d8]">{status.simulation_speed.toFixed(1)}× actual</span>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-1.5" role="group" aria-label="Simulation speed">
                {SPEED_PRESETS.map((speed) => (
                  <button
                    key={speed}
                    type="button"
                    disabled={commandPending !== null || status.state === "finished" || status.state === "error"}
                    aria-pressed={selectedSpeed === speed}
                    onClick={() => void changeSpeed(speed)}
                    className={`rounded-lg border px-2 py-2 font-mono text-xs transition ${
                      selectedSpeed === speed
                        ? "border-[#70e9a6]/60 bg-[#70e9a6]/15 text-[#8df5bb]"
                        : "border-white/[.08] bg-white/[.025] text-[#91a0a8] hover:border-white/20 hover:text-[#d7e1e6]"
                    } disabled:cursor-not-allowed disabled:opacity-35`}
                  >
                    {speed}×
                  </button>
                ))}
              </div>
              <p className="mt-2 text-[10px] leading-relaxed text-[#667781]">Select before Start or change pacing while running/paused.</p>
            </div>
            <div className="mt-5 rounded-xl border border-white/[.06] bg-black/10 p-3 text-xs leading-relaxed text-[#7f909b]">
              Reset starts a fresh SUMO run at zero and keeps it paused. Stop returns the service to idle and clears the frame.
            </div>
          </aside>

          <div className="order-1 min-h-[480px] rounded-[24px] border border-white/[.08] bg-[#10171c] p-2 shadow-2xl shadow-black/30 xl:order-2 xl:h-[calc(100vh-116px)] xl:min-h-[620px]">
            {geometry ? (
              <SimulationCanvas key={geometry.scenario_selection_id} geometry={geometry} scenario={selectedScenario} snapshot={snapshot} status={status} connection={connection} />
            ) : (
              <div className="grid h-full min-h-[470px] place-items-center rounded-[20px] bg-[#0b1115] text-sm text-[#81909a]">
                {loading ? "Loading SUMO network geometry…" : "Network geometry unavailable"}
              </div>
            )}
          </div>

          <aside className="order-3 grid content-start gap-4 sm:grid-cols-2 xl:grid-cols-1">
            <div className="rounded-[20px] border border-white/[.07] bg-[#10171c] p-4">
              <p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Live telemetry</p>
              <div className="mt-5 grid grid-cols-2 gap-3">
                <div className="rounded-xl bg-white/[.025] p-3">
                  <p className="text-[11px] text-[#73838d]">Simulation time</p>
                  <p className="mt-2 font-mono text-2xl font-medium tracking-tight">{formatTime(snapshot?.simulation_time_s ?? status.simulation_time_s)}</p>
                </div>
                <div className="rounded-xl bg-white/[.025] p-3">
                  <p className="text-[11px] text-[#73838d]">Vehicles active</p>
                  <p className="mt-2 font-mono text-2xl font-medium tracking-tight">{vehicleCount ?? "—"}</p>
                </div>
              </div>
              <div className="mt-4 border-t border-white/[.06] pt-4">
                {selectedScenarioId === "single_intersection" ? (
                  <>
                    <div className="flex justify-between text-xs"><span className="text-[#73838d]">Phase</span><span className="max-w-[165px] truncate font-mono text-[#c5d0d6]">{snapshot?.current_phase_id || "—"}</span></div>
                    <div className="mt-2 flex justify-between text-xs"><span className="text-[#73838d]">Next switch</span><span className="font-mono text-[#c5d0d6]">{snapshot?.remaining_phase_duration_s == null ? "—" : `${snapshot.remaining_phase_duration_s.toFixed(0)}s`}</span></div>
                  </>
                ) : (
                  <>
                    <div className="flex justify-between text-xs"><span className="text-[#73838d]">Controllers</span><span className="font-mono text-[#c5d0d6]">{snapshot?.traffic_light_controllers ? Object.keys(snapshot.traffic_light_controllers).length : geometry?.traffic_lights.length ?? "—"}</span></div>
                    <div className="mt-2 flex justify-between text-xs"><span className="text-[#73838d]">Network queue</span><span className="font-mono text-[#c5d0d6]">{snapshot?.network_queue?.vehicles ?? "—"}</span></div>
                  </>
                )}
                <div className="mt-2 flex justify-between text-xs"><span className="text-[#73838d]">Run</span><span className="max-w-[165px] truncate font-mono text-[10px] text-[#82939d]" title={snapshot?.run_id}>{snapshot?.run_id ?? "—"}</span></div>
              </div>
            </div>

            <div className="rounded-[20px] border border-white/[.07] bg-[#10171c] p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Queues</p>
                  <h2 className="mt-1 text-sm font-medium">Halting vehicles</h2>
                </div>
                <span className="text-[10px] text-[#667781]">SUMO</span>
              </div>
              {selectedScenarioId === "single_intersection" ? (
                <div className="mt-4 space-y-2">
                  {queueRows.map(({ approach, value }) => {
                  const maxQueue = Math.max(1, ...queueRows.map((row) => row.value ?? 0));
                  return (
                    <div key={approach} className="rounded-xl bg-white/[.025] px-3 py-2.5">
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-[#9aa8b0]">{APPROACH_LABELS[approach] ?? approach}</span>
                        <span className="font-mono text-[#dce5e9]">{value ?? "—"}</span>
                      </div>
                      <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/[.06]">
                        {value != null && <div className="h-full rounded-full bg-[#70e9a6] transition-[width] duration-300" style={{ width: `${(value / maxQueue) * 100}%` }} />}
                      </div>
                    </div>
                  );
                  })}
                </div>
              ) : (
                <div className="mt-4 rounded-xl bg-white/[.025] p-3">
                  <div className="flex items-end justify-between">
                    <span className="text-xs text-[#8797a0]">All controlled lanes</span>
                    <span className="font-mono text-2xl text-[#dce5e9]">{snapshot?.network_queue?.vehicles ?? "—"}</span>
                  </div>
                  <p className="mt-2 text-[10px] leading-relaxed text-[#667781]">Deduplicated SUMO halting count across {snapshot?.network_queue?.controlled_lane_count ?? "—"} controlled lanes.</p>
                </div>
              )}
              {!snapshot && <p className="mt-3 text-[11px] leading-relaxed text-[#667781]">No measured queue data yet. Unknown values remain distinct from zero.</p>}
            </div>

            <div className="rounded-[20px] border border-white/[.07] bg-[#10171c] p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Run metrics</p>
                  <h2 className="mt-1 text-sm font-medium">Cumulative waiting</h2>
                </div>
                <span className="rounded-full border border-white/10 px-2 py-1 font-mono text-[10px] uppercase text-[#9cacb5]">{status.control_mode ?? selectedControlMode}</span>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2">
                <div className="rounded-xl bg-white/[.025] p-3">
                  <p className="text-[10px] text-[#73838d]">Total vehicle-seconds</p>
                  <p className="mt-1 font-mono text-lg text-[#e1eaee]">{metrics ? `${metrics.total_waiting_time_s.toFixed(0)}s` : "—"}</p>
                  <p className="mt-1 text-[10px] text-[#71818a]">{formatAccumulatedTime(metrics?.total_waiting_time_s)}</p>
                </div>
                <div className="rounded-xl bg-white/[.025] p-3">
                  <p className="text-[10px] text-[#73838d]">Average / departed</p>
                  <p className="mt-1 font-mono text-lg text-[#e1eaee]">{metrics?.average_waiting_time_s == null ? "—" : `${metrics.average_waiting_time_s.toFixed(1)}s`}</p>
                  <p className="mt-1 text-[10px] text-[#71818a]">{metrics?.departed_vehicle_count ?? 0} inserted</p>
                </div>
              </div>
              <div className="mt-3 space-y-2 border-t border-white/[.06] pt-3 text-xs">
                <div className="flex justify-between"><span className="text-[#73838d]">Arrived vehicles</span><span className="font-mono text-[#c5d0d6]">{metrics?.arrived_vehicle_count ?? "—"}</span></div>
                <div className="flex justify-between"><span className="text-[#73838d]">Current queue</span><span className="font-mono text-[#c5d0d6]">{metrics?.network_queue_vehicles ?? "—"}</span></div>
                <div className="flex justify-between"><span className="text-[#73838d]">Maximum queue</span><span className="font-mono text-[#c5d0d6]">{metrics?.maximum_network_queue_vehicles ?? "—"}</span></div>
              </div>
              <p className="mt-3 text-[10px] leading-relaxed text-[#667781]">Average denominator: every vehicle inserted so far, including active and completed trips.</p>
            </div>
          </aside>
        </section>
      </div>
    </main>
  );
}
