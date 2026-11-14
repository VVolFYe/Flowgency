"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, WS_URL } from "@/lib/api";
import type {
  NetworkGeometry,
  SimulationScenario,
  SimulationSnapshot,
  SimulationStatus,
  StreamEnvelope,
  Vehicle,
} from "@/lib/contracts";

export type ConnectionState = "connecting" | "connected" | "reconnecting" | "offline";
export type SimulationCommand = "start" | "pause" | "resume" | "reset" | "stop";
export type ControlMode = "fixed" | "adaptive" | "adaptive_with_emergency_priority";
export type PendingCommand = SimulationCommand | "speed";
export type VehicleFrame = Map<string, Vehicle>;

export interface Transition {
  from: VehicleFrame;
  to: VehicleFrame;
  startedAt: number;
  durationMs: number;
  runId: string;
}

export interface HistoryPoint {
  runId: string;
  simulationTimeS: number;
  vehicleCount: number | null;
  queues: Record<string, number | null>;
}

interface SimulationContextValue {
  geometry: NetworkGeometry | null;
  scenarios: SimulationScenario[];
  selectedScenarioId: string;
  selectedScenario: SimulationScenario | null;
  selectedSpeed: number;
  selectedControlMode: ControlMode;
  status: SimulationStatus;
  snapshot: SimulationSnapshot | null;
  connection: ConnectionState;
  loading: boolean;
  commandPending: PendingCommand | null;
  error: string | null;
  history: HistoryPoint[];
  transitionRef: React.MutableRefObject<Transition | null>;
  execute: (command: SimulationCommand) => Promise<void>;
  changeScenario: (scenarioId: string) => Promise<void>;
  changeSpeed: (speed: number) => Promise<void>;
  setSelectedControlMode: (mode: ControlMode) => void;
  dismissError: () => void;
}

export const EMPTY_STATUS: SimulationStatus = {
  state: "idle",
  simulation_speed: 4,
  control_mode: "fixed",
  scenario_id: "single_intersection",
  simulation_time_s: null,
  has_snapshot: false,
  error: null,
};

const HISTORY_KEY = "flowgency.operator.analytics.v1";
const MAX_HISTORY_POINTS = 600;
const SimulationContext = createContext<SimulationContextValue | null>(null);

export const vehicleMap = (vehicles: Vehicle[] | undefined): VehicleFrame =>
  new Map((vehicles ?? []).map((vehicle) => [vehicle.vehicle_id, vehicle]));

const interpolateAngle = (from: number, to: number, progress: number) => {
  const delta = ((to - from + 540) % 360) - 180;
  return from + delta * progress;
};

export function interpolatedVehicles(transition: Transition, now: number): VehicleFrame {
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

function readStoredHistory(): HistoryPoint[] {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(HISTORY_KEY) ?? "[]") as unknown;
    return Array.isArray(parsed) ? (parsed as HistoryPoint[]).slice(-MAX_HISTORY_POINTS) : [];
  } catch {
    return [];
  }
}

export function SimulationProvider({ children, collectHistory = false }: { children: React.ReactNode; collectHistory?: boolean }) {
  const [geometry, setGeometry] = useState<NetworkGeometry | null>(null);
  const [scenarios, setScenarios] = useState<SimulationScenario[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState("single_intersection");
  const [selectedSpeed, setSelectedSpeed] = useState(4);
  const [selectedControlMode, setSelectedControlMode] = useState<ControlMode>("fixed");
  const [status, setStatus] = useState<SimulationStatus>(EMPTY_STATUS);
  const [snapshot, setSnapshot] = useState<SimulationSnapshot | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [loading, setLoading] = useState(true);
  const [commandPending, setCommandPending] = useState<PendingCommand | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const transitionRef = useRef<Transition | null>(null);
  const snapshotRef = useRef<SimulationSnapshot | null>(null);
  const connectionRef = useRef<ConnectionState>("connecting");
  const statusRef = useRef<SimulationStatus>(EMPTY_STATUS);
  const selectedScenarioRef = useRef("single_intersection");
  const geometryRequestRef = useRef(0);
  const lastSnapshotAtRef = useRef(0);

  useEffect(() => {
    if (!collectHistory) return;
    const timer = window.setTimeout(() => setHistory(readStoredHistory()), 0);
    return () => window.clearTimeout(timer);
  }, [collectHistory]);

  const recordHistory = useCallback((next: SimulationSnapshot) => {
    if (!collectHistory) return;
    const point: HistoryPoint = {
      runId: next.run_id,
      simulationTimeS: next.simulation_time_s,
      vehicleCount: next.vehicles ? next.vehicles.length : null,
      queues: Object.fromEntries(
        Object.entries(next.queue_lengths_by_approach).map(([approach, value]) => [approach, value?.vehicles ?? null]),
      ),
    };
    setHistory((current) => {
      const sameRun = current.length > 0 && current[current.length - 1].runId === point.runId;
      const base = sameRun ? current : [];
      if (base.at(-1)?.simulationTimeS === point.simulationTimeS) return base;
      const updated = [...base, point].slice(-MAX_HISTORY_POINTS);
      try { sessionStorage.setItem(HISTORY_KEY, JSON.stringify(updated)); } catch { /* storage is optional */ }
      return updated;
    });
  }, [collectHistory]);

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
    setSelectedSpeed(next.simulation_speed);
    if (next.state !== "idle" && next.control_mode) setSelectedControlMode(next.control_mode);
    if (!next.has_snapshot || next.state === "idle") {
      snapshotRef.current = null;
      transitionRef.current = null;
      setSnapshot(null);
    }
    if (next.error) setError(next.error);
  }, []);

  const receiveSnapshot = useCallback((next: SimulationSnapshot, animate = true) => {
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
    const now = performance.now();
    const nextVehicles = vehicleMap(next.vehicles);
    const sameRun = previous?.run_id === next.run_id && previousScenario === nextScenario;

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
    recordHistory(next);
  }, [recordHistory]);

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
    if (status.state === "idle" || status.scenario_id === selectedScenarioRef.current) return;
    selectedScenarioRef.current = status.scenario_id;
    setSelectedScenarioId(status.scenario_id);
    snapshotRef.current = null;
    transitionRef.current = null;
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
        reconnectTimer = setTimeout(connect, Math.min(10000, 500 * 2 ** Math.min(attempt, 5)));
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

  const execute = async (command: SimulationCommand) => {
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
      if (command === "stop") {
        snapshotRef.current = null;
        transitionRef.current = null;
        setSnapshot(null);
        selectedScenarioRef.current = nextStatus.scenario_id;
        setSelectedScenarioId(nextStatus.scenario_id);
        await loadGeometry(nextStatus.scenario_id);
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

  const changeSpeed = async (speed: number) => {
    setSelectedSpeed(speed);
    if (statusRef.current.state === "idle") return;
    setCommandPending("speed");
    setError(null);
    try {
      const nextStatus = await api.setSpeed(speed);
      updateStatus(nextStatus);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not change simulation speed");
      setSelectedSpeed(statusRef.current.simulation_speed);
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
    transitionRef.current = null;
    setSnapshot(null);
    setError(null);
    await loadGeometry(scenarioId);
  };

  const selectedScenario = scenarios.find((scenario) => scenario.scenario_id === selectedScenarioId) ?? null;

  return (
    <SimulationContext.Provider value={{
      geometry, scenarios, selectedScenarioId, selectedScenario, selectedSpeed, selectedControlMode,
      status, snapshot, connection, loading, commandPending, error, history,
      transitionRef, execute, changeScenario, changeSpeed, setSelectedControlMode,
      dismissError: () => setError(null),
    }}>
      {children}
    </SimulationContext.Provider>
  );
}

export function useSimulation() {
  const value = useContext(SimulationContext);
  if (!value) throw new Error("useSimulation must be used inside SimulationProvider");
  return value;
}
