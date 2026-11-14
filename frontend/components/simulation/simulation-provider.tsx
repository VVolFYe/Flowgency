"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, WS_URL } from "@/lib/api";
import type {
  ConfigurationOptions,
  ControllerMode,
  NetworkGeometry,
  NetworkId,
  SimulationConfiguration,
  SimulationScenario,
  SimulationSnapshot,
  SimulationStatus,
  StreamEnvelope,
  TrafficProfile,
  Vehicle,
} from "@/lib/contracts";

export type ConnectionState = "connecting" | "connected" | "reconnecting" | "offline";
export type SimulationCommand = "start" | "pause" | "resume" | "reset" | "stop";
export type { ControllerMode as ControlMode } from "@/lib/contracts";
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
  emergencyVehicleCount: number;
  priorityRequestCount: number;
}

interface SimulationContextValue {
  geometry: NetworkGeometry | null;
  configurationOptions: ConfigurationOptions | null;
  selectedScenarioId: string;
  selectedScenario: SimulationScenario | null;
  selectedConfiguration: SimulationConfiguration;
  selectedSpeed: number;
  selectedControlMode: ControllerMode;
  status: SimulationStatus;
  snapshot: SimulationSnapshot | null;
  connection: ConnectionState;
  loading: boolean;
  commandPending: PendingCommand | null;
  error: string | null;
  history: HistoryPoint[];
  transitionRef: React.MutableRefObject<Transition | null>;
  execute: (command: SimulationCommand) => Promise<void>;
  changeNetwork: (network: NetworkId) => Promise<void>;
  setSelectedTrafficProfile: (profile: TrafficProfile) => void;
  setEmergencyVehiclesEnabled: (enabled: boolean) => void;
  changeSpeed: (speed: number) => Promise<void>;
  setSelectedControlMode: (mode: ControllerMode) => void;
  dismissError: () => void;
}

export const EMPTY_STATUS: SimulationStatus = {
  state: "idle",
  simulation_speed: 4,
  active_configuration: null,
  network: null,
  traffic_profile: null,
  controller_mode: null,
  emergency_vehicles_enabled: null,
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
  const [configurationOptions, setConfigurationOptions] = useState<ConfigurationOptions | null>(null);
  const [selectedScenarioId, setSelectedScenarioId] = useState("single_intersection");
  const [selectedTrafficProfile, setSelectedTrafficProfile] = useState<TrafficProfile>("normal");
  const [emergencyVehiclesEnabled, setEmergencyVehiclesEnabled] = useState(false);
  const [selectedSpeed, setSelectedSpeed] = useState(4);
  const [selectedControlMode, setSelectedControlMode] = useState<ControllerMode>("fixed_timing");
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
  const selectedNetworkRef = useRef<NetworkId>("single_intersection");
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
      emergencyVehicleCount: next.vehicles?.filter((vehicle) => vehicle.is_emergency).length ?? 0,
      priorityRequestCount: next.emergency_events?.filter((event) => event.state === "priority_active").length ?? 0,
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
    if (!next.has_snapshot || next.state === "idle") {
      snapshotRef.current = null;
      transitionRef.current = null;
      setSnapshot(null);
    }
    if (next.error) setError(next.error);
  }, []);

  const receiveSnapshot = useCallback((next: SimulationSnapshot, animate = true) => {
    const previous = snapshotRef.current;
    const nextScenario = next.active_configuration.network;
    const previousScenario = previous?.active_configuration.network;
    if (statusRef.current.active_configuration && nextScenario !== statusRef.current.active_configuration.network) return;
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
    Promise.all([api.configurationOptions(), api.status()])
      .then(async ([availableOptions, initialStatus]) => {
        if (cancelled) return;
        const active = initialStatus.active_configuration;
        const network = active?.network ?? "single_intersection";
        setConfigurationOptions(availableOptions);
        setSelectedScenarioId(network);
        selectedNetworkRef.current = network;
        if (active) {
          setSelectedTrafficProfile(active.traffic_profile);
          setSelectedControlMode(active.controller_mode);
          setEmergencyVehiclesEnabled(active.emergency_vehicles_enabled);
        }
        updateStatus(initialStatus);
        setSelectedSpeed(initialStatus.simulation_speed);
        const [networkGeometry, initialSnapshot] = await Promise.all([
          api.network(active?.network ?? "single_intersection"),
          initialStatus.has_snapshot ? api.snapshot() : Promise.resolve(null),
        ]);
        if (cancelled) return;
        setGeometry(networkGeometry);
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
    const activeNetwork = status.active_configuration?.network;
    if (!activeNetwork || activeNetwork === selectedNetworkRef.current) return;
    selectedNetworkRef.current = activeNetwork;
    setSelectedScenarioId(activeNetwork);
    snapshotRef.current = null;
    transitionRef.current = null;
    setSnapshot(null);
    void loadGeometry(activeNetwork);
  }, [loadGeometry, status.active_configuration]);

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
        command === "start" ? {
          network: selectedNetworkRef.current,
          traffic_profile: selectedTrafficProfile,
          controller_mode: selectedControlMode,
          emergency_vehicles_enabled: emergencyVehiclesEnabled,
        } : undefined,
      );
      updateStatus(nextStatus);
      if (command === "stop") {
        snapshotRef.current = null;
        transitionRef.current = null;
        setSnapshot(null);
        await loadGeometry(selectedNetworkRef.current);
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

  const changeNetwork = async (network: NetworkId) => {
    if (statusRef.current.state !== "idle" || commandPending) return;
    selectedNetworkRef.current = network;
    setSelectedScenarioId(network);
    snapshotRef.current = null;
    transitionRef.current = null;
    setSnapshot(null);
    setError(null);
    await loadGeometry(network);
  };

  const selectedScenario: SimulationScenario = {
    scenario_id: selectedScenarioId,
    display_name: selectedScenarioId === "london" ? "London Network" : "Single Intersection",
    description: selectedScenarioId === "london"
      ? "Connected Oval/Kennington SUMO network."
      : "Synthetic four-approach SUMO intersection.",
    coordinate_system: geometry?.coordinate_system ?? "",
    supports_adaptive_control: true,
    supports_emergency_priority: true,
    known_limitation: null,
    target_mappings: [],
  };
  const selectedConfiguration: SimulationConfiguration = {
    network: selectedScenarioId as NetworkId,
    traffic_profile: selectedTrafficProfile,
    controller_mode: selectedControlMode,
    emergency_vehicles_enabled: emergencyVehiclesEnabled,
  };

  return (
    <SimulationContext.Provider value={{
      geometry, configurationOptions, selectedScenarioId, selectedScenario, selectedConfiguration, selectedSpeed, selectedControlMode,
      status, snapshot, connection, loading, commandPending, error, history,
      transitionRef, execute, changeNetwork, changeSpeed, setSelectedControlMode,
      setSelectedTrafficProfile, setEmergencyVehiclesEnabled,
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
