"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, BACKEND_URL, WS_URL } from "@/lib/api";
import { SiteNav } from "@/components/site-nav";
import type {
  Lane,
  NetworkGeometry,
  ServiceState,
  SimulationSnapshot,
  SimulationStatus,
  StreamEnvelope,
  Vehicle,
} from "@/lib/contracts";

type ConnectionState = "connecting" | "connected" | "reconnecting" | "offline";
type VehicleFrame = Map<string, Vehicle>;

interface Transition {
  from: VehicleFrame;
  to: VehicleFrame;
  startedAt: number;
  durationMs: number;
  runId: string;
}

const EMPTY_STATUS: SimulationStatus = {
  state: "idle",
  simulation_speed: 4,
  simulation_time_s: null,
  has_snapshot: false,
  error: null,
};

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

const vehicleMap = (vehicles: Vehicle[] | undefined): VehicleFrame =>
  new Map((vehicles ?? []).map((vehicle) => [vehicle.vehicle_id, vehicle]));

const interpolateAngle = (from: number, to: number, progress: number) => {
  const delta = ((to - from + 540) % 360) - 180;
  return from + delta * progress;
};

function interpolatedVehicles(transition: Transition, now: number): VehicleFrame {
  if (transition.durationMs <= 0) return transition.to;
  const progress = Math.min(1, Math.max(0, (now - transition.startedAt) / transition.durationMs));
  const result = new Map<string, Vehicle>();
  transition.to.forEach((target, id) => {
    const source = transition.from.get(id) ?? target;
    result.set(id, {
      ...target,
      x_m: source.x_m + (target.x_m - source.x_m) * progress,
      y_m: source.y_m + (target.y_m - source.y_m) * progress,
      angle_deg: interpolateAngle(source.angle_deg, target.angle_deg, progress),
    });
  });
  return result;
}

function formatTime(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  const remainder = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}

function signalColor(state: string | undefined) {
  if (state === "G" || state === "g") return "#61f69b";
  if (state === "y" || state === "Y") return "#f3bd4b";
  if (state === "r" || state === "R") return "#ff5964";
  return "#53616c";
}

function drawRoundedRect(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  context.beginPath();
  context.roundRect(x, y, width, height, radius);
}

function SimulationCanvas({
  geometry,
  snapshot,
  status,
  connection,
  transitionRef,
}: {
  geometry: NetworkGeometry;
  snapshot: SimulationSnapshot | null;
  status: SimulationStatus;
  connection: ConnectionState;
  transitionRef: React.MutableRefObject<Transition | null>;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const sizeRef = useRef({ width: 0, height: 0 });

  const draw = useCallback((now: number) => {
    const canvas = canvasRef.current;
    const { width, height } = sizeRef.current;
    if (!canvas || width <= 0 || height <= 0) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const pixelRatio = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(width * pixelRatio) || canvas.height !== Math.round(height * pixelRatio)) {
      canvas.width = Math.round(width * pixelRatio);
      canvas.height = Math.round(height * pixelRatio);
    }
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);

    const padding = Math.max(28, Math.min(width, height) * 0.075);
    const bounds = geometry.bounds;
    const worldWidth = Math.max(1, bounds.max_x_m - bounds.min_x_m);
    const worldHeight = Math.max(1, bounds.max_y_m - bounds.min_y_m);
    const scale = Math.min((width - padding * 2) / worldWidth, (height - padding * 2) / worldHeight);
    const offsetX = (width - worldWidth * scale) / 2;
    const offsetY = (height - worldHeight * scale) / 2;
    const screen = (point: { x_m: number; y_m: number }) => ({
      x: offsetX + (point.x_m - bounds.min_x_m) * scale,
      y: height - offsetY - (point.y_m - bounds.min_y_m) * scale,
    });

    const grid = Math.max(25, worldWidth / 12);
    context.strokeStyle = "rgba(121, 152, 169, .055)";
    context.lineWidth = 1;
    for (let x = Math.ceil(bounds.min_x_m / grid) * grid; x <= bounds.max_x_m; x += grid) {
      const start = screen({ x_m: x, y_m: bounds.min_y_m });
      const end = screen({ x_m: x, y_m: bounds.max_y_m });
      context.beginPath(); context.moveTo(start.x, start.y); context.lineTo(end.x, end.y); context.stroke();
    }
    for (let y = Math.ceil(bounds.min_y_m / grid) * grid; y <= bounds.max_y_m; y += grid) {
      const start = screen({ x_m: bounds.min_x_m, y_m: y });
      const end = screen({ x_m: bounds.max_x_m, y_m: y });
      context.beginPath(); context.moveTo(start.x, start.y); context.lineTo(end.x, end.y); context.stroke();
    }

    geometry.junctions.forEach((junction) => {
      if (junction.shape.length < 3) return;
      context.beginPath();
      junction.shape.forEach((point, index) => {
        const position = screen(point);
        if (index === 0) context.moveTo(position.x, position.y);
        else context.lineTo(position.x, position.y);
      });
      context.closePath();
      context.fillStyle = junction.type === "traffic_light" ? "#202c34" : "#161f25";
      context.fill();
      context.strokeStyle = "#34434d";
      context.stroke();
    });

    const lanes = geometry.edges.flatMap((edge) => edge.lanes.map((lane) => ({ lane, internal: edge.is_internal })));
    lanes.forEach(({ lane, internal }) => {
      if (lane.shape.length < 2) return;
      context.beginPath();
      lane.shape.forEach((point, index) => {
        const position = screen(point);
        if (index === 0) context.moveTo(position.x, position.y);
        else context.lineTo(position.x, position.y);
      });
      context.lineWidth = Math.max(3, lane.width_m * scale);
      context.lineCap = "round";
      context.lineJoin = "round";
      context.strokeStyle = internal ? "#35434b" : "#2c3941";
      context.stroke();
      context.lineWidth = 1;
      context.setLineDash(internal ? [3, 4] : [7, 8]);
      context.strokeStyle = internal ? "rgba(186, 207, 216, .22)" : "rgba(186, 207, 216, .32)";
      context.stroke();
      context.setLineDash([]);
    });

    const laneById = new Map<string, Lane>();
    geometry.edges.forEach((edge) => edge.lanes.forEach((lane) => laneById.set(lane.lane_id, lane)));
    const junction = geometry.junctions.find((item) => item.type === "traffic_light");
    const center = junction ? { x_m: junction.x_m, y_m: junction.y_m } : {
      x_m: (bounds.min_x_m + bounds.max_x_m) / 2,
      y_m: (bounds.min_y_m + bounds.max_y_m) / 2,
    };
    const grouped = new Map<string, typeof geometry.controlled_links>();
    geometry.controlled_links.forEach((link) => grouped.set(link.from_lane, [...(grouped.get(link.from_lane) ?? []), link]));
    grouped.forEach((links, laneId) => {
      const lane = laneById.get(laneId);
      if (!lane || lane.shape.length < 2) return;
      const sorted = [...lane.shape].sort((a, b) =>
        Math.hypot(a.x_m - center.x_m, a.y_m - center.y_m) - Math.hypot(b.x_m - center.x_m, b.y_m - center.y_m));
      const near = sorted[0];
      const next = sorted[1];
      const length = Math.max(0.001, Math.hypot(next.x_m - near.x_m, next.y_m - near.y_m));
      const ux = (next.x_m - near.x_m) / length;
      const uy = (next.y_m - near.y_m) / length;
      links.sort((a, b) => a.link_index - b.link_index).forEach((link, index) => {
        const spread = (index - (links.length - 1) / 2) * 3.3;
        const position = screen({
          x_m: near.x_m + ux * 5 - uy * spread,
          y_m: near.y_m + uy * 5 + ux * spread,
        });
        const color = signalColor(snapshot?.traffic_light_state?.[link.link_index]);
        context.beginPath(); context.arc(position.x, position.y, 7, 0, Math.PI * 2);
        context.fillStyle = "#071014"; context.fill();
        context.lineWidth = 2; context.strokeStyle = "#65737c"; context.stroke();
        context.beginPath(); context.arc(position.x, position.y, 4, 0, Math.PI * 2);
        context.fillStyle = color; context.shadowColor = color; context.shadowBlur = 9; context.fill(); context.shadowBlur = 0;
      });
    });

    const transition = transitionRef.current;
    const vehicles = transition ? interpolatedVehicles(transition, now) : vehicleMap(snapshot?.vehicles);
    vehicles.forEach((vehicle) => {
      const position = screen(vehicle);
      const length = Math.max(7, 4.6 * scale);
      const vehicleWidth = Math.max(4, 1.9 * scale);
      context.save();
      context.translate(position.x, position.y);
      context.rotate((vehicle.angle_deg * Math.PI) / 180);
      drawRoundedRect(context, -vehicleWidth / 2, -length / 2, vehicleWidth, length, Math.min(2.5, vehicleWidth / 2));
      context.fillStyle = vehicle.vehicle_type.toLowerCase().includes("bus") ? "#f3bd4b" : "#dce9ef";
      context.shadowColor = "rgba(115, 226, 255, .55)"; context.shadowBlur = 5; context.fill();
      context.shadowBlur = 0;
      context.fillStyle = "#1c657c";
      context.fillRect(-vehicleWidth * .32, -length * .24, vehicleWidth * .64, length * .19);
      context.restore();
    });
  }, [geometry, snapshot, transitionRef]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const resize = new ResizeObserver(([entry]) => {
      sizeRef.current = { width: entry.contentRect.width, height: entry.contentRect.height };
      draw(performance.now());
    });
    resize.observe(host);
    return () => resize.disconnect();
  }, [draw]);

  useEffect(() => {
    let frame = 0;
    const animate = (now: number) => {
      draw(now);
      const transition = transitionRef.current;
      if (status.state === "running" && connection === "connected" && transition && now < transition.startedAt + transition.durationMs) {
        frame = requestAnimationFrame(animate);
      }
    };
    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  }, [connection, draw, snapshot, status.state, transitionRef]);

  return (
    <div ref={hostRef} className="relative h-full min-h-[390px] overflow-hidden rounded-[20px] bg-[#0b1115]">
      <canvas ref={canvasRef} className="block h-full w-full" aria-label="Live SUMO intersection map" />
      <div className="pointer-events-none absolute left-4 top-4 rounded-lg border border-white/10 bg-[#0b1115]/80 px-3 py-2 backdrop-blur">
        <div className="font-mono text-[10px] uppercase tracking-[.18em] text-[#7f909b]">SUMO Cartesian</div>
        <div className="mt-1 text-xs text-[#b8c5cc]">{geometry.scenario_id}</div>
      </div>
      {!snapshot && status.state !== "idle" && (
        <div className="absolute inset-0 grid place-items-center bg-[#0b1115]/60 text-sm text-[#9cabb4]">
          Waiting for first SUMO snapshot…
        </div>
      )}
    </div>
  );
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
  const [status, setStatus] = useState<SimulationStatus>(EMPTY_STATUS);
  const [snapshot, setSnapshot] = useState<SimulationSnapshot | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [loading, setLoading] = useState(true);
  const [commandPending, setCommandPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const transitionRef = useRef<Transition | null>(null);
  const snapshotRef = useRef<SimulationSnapshot | null>(null);
  const connectionRef = useRef<ConnectionState>("connecting");
  const statusRef = useRef<SimulationStatus>(EMPTY_STATUS);
  const lastSnapshotAtRef = useRef(0);

  const updateStatus = useCallback((next: SimulationStatus) => {
    statusRef.current = next;
    setStatus(next);
    if (!next.has_snapshot || next.state === "idle") {
      snapshotRef.current = null;
      transitionRef.current = null;
      setSnapshot(null);
    }
    if (next.error) setError(next.error);
  }, []);

  const receiveSnapshot = useCallback((next: SimulationSnapshot, animate = true) => {
    const previous = snapshotRef.current;
    const now = performance.now();
    const nextVehicles = vehicleMap(next.vehicles);
    const sameRun = previous?.run_id === next.run_id;
    const isNewFrame = !previous || !sameRun || next.simulation_time_s !== previous.simulation_time_s;

    if (!isNewFrame) return;
    const canAnimate = animate && sameRun && statusRef.current.state === "running" && connectionRef.current === "connected";
    let from = nextVehicles;
    if (canAnimate && transitionRef.current) from = interpolatedVehicles(transitionRef.current, now);
    else if (canAnimate && previous) from = vehicleMap(previous.vehicles);
    const elapsed = lastSnapshotAtRef.current ? now - lastSnapshotAtRef.current : 250;
    transitionRef.current = {
      from,
      to: nextVehicles,
      startedAt: now,
      durationMs: canAnimate ? Math.min(600, Math.max(120, elapsed)) : 0,
      runId: next.run_id,
    };
    lastSnapshotAtRef.current = now;
    snapshotRef.current = next;
    setSnapshot(next);
  }, []);

  const refreshHttp = useCallback(async (includeSnapshot = false) => {
    const nextStatus = await api.status();
    updateStatus(nextStatus);
    if (includeSnapshot || nextStatus.has_snapshot) {
      const latest = await api.snapshot();
      if (latest) receiveSnapshot(latest, false);
    }
  }, [receiveSnapshot, updateStatus]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.network(), api.status(), api.snapshot()])
      .then(([network, initialStatus, initialSnapshot]) => {
        if (cancelled) return;
        setGeometry(network);
        updateStatus(initialStatus);
        if (initialSnapshot) receiveSnapshot(initialSnapshot, false);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Failed to load simulation");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [receiveSnapshot, updateStatus]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;
    let attempt = 0;

    const setConnectionState = (next: ConnectionState) => {
      connectionRef.current = next;
      setConnection(next);
      if (next !== "connected" && transitionRef.current) {
        transitionRef.current = { ...transitionRef.current, from: transitionRef.current.to, durationMs: 0 };
      }
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
      const nextStatus = await api.command(command);
      updateStatus(nextStatus);
      if (command === "stop") {
        snapshotRef.current = null;
        transitionRef.current = null;
        setSnapshot(null);
      } else {
        const latest = await api.snapshot();
        if (latest) receiveSnapshot(latest, false);
      }
      await refreshHttp(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `Could not ${command} simulation`);
      try { await refreshHttp(true); } catch { /* retain command error */ }
    } finally {
      setCommandPending(null);
    }
  };

  const queueRows = useMemo(() => {
    const known = snapshot?.queue_lengths_by_approach;
    const approaches = geometry
      ? Array.from(new Set(geometry.controlled_links.map((link) => link.approach)))
      : Object.keys(APPROACH_LABELS);
    return approaches.map((approach) => ({ approach, value: known?.[approach]?.vehicles ?? null }));
  }, [geometry, snapshot]);

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
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
              <ControlButton label="Start simulation" action="Start" primary enabled={status.state === "idle"} busy={commandPending !== null} onClick={() => execute("start")} />
              <ControlButton label="Pause" action="Pause" enabled={status.state === "running"} busy={commandPending !== null} onClick={() => execute("pause")} />
              <ControlButton label="Resume" action="Play" enabled={status.state === "paused"} busy={commandPending !== null} onClick={() => execute("resume")} />
              <ControlButton label="New run at 00:00" action="Reset" enabled={status.state !== "idle"} busy={commandPending !== null} onClick={() => execute("reset")} />
              <ControlButton label="Stop & clear" action="Stop" enabled={status.state !== "idle"} busy={commandPending !== null} onClick={() => execute("stop")} />
            </div>
            <div className="mt-5 rounded-xl border border-white/[.06] bg-black/10 p-3 text-xs leading-relaxed text-[#7f909b]">
              Reset starts a fresh SUMO run at zero and keeps it paused. Stop returns the service to idle and clears the frame.
            </div>
            <div className="mt-4 flex items-center justify-between border-t border-white/[.06] pt-4 text-xs">
              <span className="text-[#6f808a]">Simulation speed</span>
              <span className="font-mono text-[#c7d2d8]">{status.simulation_speed.toFixed(1)}×</span>
            </div>
          </aside>

          <div className="order-1 min-h-[480px] rounded-[24px] border border-white/[.08] bg-[#10171c] p-2 shadow-2xl shadow-black/30 xl:order-2 xl:h-[calc(100vh-116px)] xl:min-h-[620px]">
            {geometry ? (
              <SimulationCanvas geometry={geometry} snapshot={snapshot} status={status} connection={connection} transitionRef={transitionRef} />
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
                <div className="flex justify-between text-xs"><span className="text-[#73838d]">Phase</span><span className="max-w-[165px] truncate font-mono text-[#c5d0d6]">{snapshot?.current_phase_id || "—"}</span></div>
                <div className="mt-2 flex justify-between text-xs"><span className="text-[#73838d]">Next switch</span><span className="font-mono text-[#c5d0d6]">{snapshot?.remaining_phase_duration_s == null ? "—" : `${snapshot.remaining_phase_duration_s.toFixed(0)}s`}</span></div>
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
              {!snapshot && <p className="mt-3 text-[11px] leading-relaxed text-[#667781]">No measured queue data yet. Unknown values remain distinct from zero.</p>}
            </div>
          </aside>
        </section>
      </div>
    </main>
  );
}
