import type { NetworkGeometry } from "./contracts";

export const REPLAY_SCHEMA_VERSION = "1.0";
export const VIDEO_SOURCES = ["original_video", "annotated_video"] as const;
export type VideoSource = (typeof VIDEO_SOURCES)[number];

/** Allowlisted AI Traffic datasets; the backend maps each to a fixed bundle directory. */
export const REPLAY_DATASET_IDS = ["demo1", "demo2"] as const;
export type ReplayDatasetId = (typeof REPLAY_DATASET_IDS)[number];
export const DEFAULT_REPLAY_DATASET_ID: ReplayDatasetId = "demo1";
/** User-facing intersection names. Display only: IDs, routes and bundles keep demo1/demo2. */
export const REPLAY_DATASET_LABELS: Record<ReplayDatasetId, string> = {
  demo1: "Center Street & 500 West Intersection",
  demo2: "Center Street & University Avenue Intersection",
};
export const REPLAY_DATASET_SHORT_LABELS: Record<ReplayDatasetId, string> = {
  demo1: "Intersection 1",
  demo2: "Intersection 2",
};

export interface ReplayDatasetStatus {
  dataset_id: ReplayDatasetId;
  label: string;
  description: string;
  default: boolean;
  available: boolean;
  detail: string | null;
  video_sources: VideoSource[];
}

export interface ReplayVehicle {
  vehicle_id: string;
  x_m: number;
  y_m: number;
  angle_deg: number;
  speed_mps: number;
  lane_id: string;
  edge_id: string;
}

export interface ReplayTrafficLight {
  traffic_light_id: string;
  phase_index: number;
  phase_id: string;
  state: string;
}

export interface ReplayMetrics {
  cumulative_waiting_time_s: number;
  active_vehicle_count: number;
  arrived_vehicle_count: number;
  measurement: "sum_waiting_vehicle_intervals_x_step_duration";
}

export interface ReplayFrame {
  schema_version: "1.0";
  record_type: "frame";
  frame_index: number;
  simulation_time_s: number;
  coordinate_system: string;
  vehicles: ReplayVehicle[];
  traffic_lights: ReplayTrafficLight[];
  metrics?: ReplayMetrics;
}

export interface ReplayStream {
  frames: ReplayFrame[];
  vehicleIds: Set<string>;
  durationS: number;
  coordinateSystem: string;
  waitingSeriesAvailable: boolean;
}

export interface AssetStatus {
  available: boolean;
  url: string | null;
  duration_s?: number;
  frame_count?: number;
  waiting_series_available?: boolean;
}

export interface MetricComparison {
  fixed: number;
  adaptive: number;
  adaptive_minus_fixed: number;
  improvement_percent: number | null;
  outcome: "improvement" | "regression" | "no_change";
}

export interface ReplayManifest {
  schema_version: "1.0";
  dataset_id: string;
  display_name: string;
  /** Allowlisted selection the manifest was served for (dataset-scoped endpoints only). */
  selection_id?: string;
  video: {
    /** Original footage duration; null when no original video exists (annotated-only). */
    duration_s: number | null;
    annotated_duration_s: number;
    camera_orientation_verified: boolean;
    source_kind?: "annotated_only";
    original_video_available?: boolean;
  };
  network_geometry: {
    scenario_id: "single_intersection";
    coordinate_system: "synthetic_cartesian_metres";
  };
  assets: Record<
    "original_video" | "annotated_video" | "fixed_replay" | "gap_v1_replay",
    AssetStatus
  >;
  replays: {
    fixed: {
      simulation_duration_s: number;
      strategy: "fixed";
      waiting_time_series?: { available: boolean; final_cumulative_waiting_time_s: number | null };
    };
    gap_v1: {
      simulation_duration_s: number;
      strategy: "gap_v1";
      controller_provenance: {
        selected_strategy: "gap_v1";
        active_strategy_verified_at_runtime: boolean;
        active_traffic_light_ids: string[];
        validation_errors: string[];
      };
      waiting_time_series?: { available: boolean; final_cumulative_waiting_time_s: number | null };
    };
  };
  comparison: {
    validation: { passed: boolean; collisions: number; teleports: number };
    inputs: { vehicle_count: number };
    runs: Record<"fixed" | "adaptive", Record<string, number>>;
    comparison: Record<string, MetricComparison>;
    adaptive_controller: {
      selected_strategy: "gap_v1";
      active_strategy_verified_at_runtime: boolean;
      active_traffic_light_ids: string[];
    };
  };
  limitations: string[];
}

const finiteNumber = (value: unknown, field: string) => {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`Replay ${field} must be a finite number`);
  }
  return value;
};

const objectValue = (value: unknown, field: string): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`Replay ${field} must be an object`);
  }
  return value as Record<string, unknown>;
};

function parseVehicle(value: unknown, line: number): ReplayVehicle {
  const vehicle = objectValue(value, `vehicle on line ${line}`);
  if (typeof vehicle.vehicle_id !== "string" || !vehicle.vehicle_id) {
    throw new Error(`Replay vehicle ID is invalid on line ${line}`);
  }
  if (typeof vehicle.lane_id !== "string" || typeof vehicle.edge_id !== "string") {
    throw new Error(`Replay vehicle lane/edge is invalid on line ${line}`);
  }
  return {
    vehicle_id: vehicle.vehicle_id,
    x_m: finiteNumber(vehicle.x_m, "vehicle.x_m"),
    y_m: finiteNumber(vehicle.y_m, "vehicle.y_m"),
    angle_deg: finiteNumber(vehicle.angle_deg, "vehicle.angle_deg"),
    speed_mps: finiteNumber(vehicle.speed_mps, "vehicle.speed_mps"),
    lane_id: vehicle.lane_id,
    edge_id: vehicle.edge_id,
  };
}

function parseTrafficLight(value: unknown, line: number): ReplayTrafficLight {
  const light = objectValue(value, `traffic light on line ${line}`);
  if (
    typeof light.traffic_light_id !== "string" ||
    !light.traffic_light_id ||
    !Number.isInteger(light.phase_index) ||
    typeof light.phase_id !== "string" ||
    typeof light.state !== "string" ||
    !light.state
  ) {
    throw new Error(`Replay traffic-light state is invalid on line ${line}`);
  }
  return {
    traffic_light_id: light.traffic_light_id,
    phase_index: light.phase_index as number,
    phase_id: light.phase_id,
    state: light.state,
  };
}

export function parseReplayJsonl(
  text: string,
  expected: {
    frameCount?: number;
    durationS?: number;
    coordinateSystem: string;
    trafficLightId: string;
  },
): ReplayStream {
  const lines = text.split(/\r?\n/).filter((line) => line.trim().length > 0);
  if (!lines.length) throw new Error("Replay stream is empty");
  const frames: ReplayFrame[] = [];
  const vehicleIds = new Set<string>();
  let previousTime = -Infinity;
  let previousWaiting: number | null = null;
  let waitingSamples = 0;
  lines.forEach((line, index) => {
    let raw: unknown;
    try {
      raw = JSON.parse(line);
    } catch {
      throw new Error(`Replay contains invalid JSON on line ${index + 1}`);
    }
    const frame = objectValue(raw, `frame on line ${index + 1}`);
    if (
      frame.schema_version !== REPLAY_SCHEMA_VERSION ||
      frame.record_type !== "frame" ||
      frame.frame_index !== index
    ) {
      throw new Error(`Replay frame schema/index is invalid on line ${index + 1}`);
    }
    const time = finiteNumber(frame.simulation_time_s, "simulation_time_s");
    if (time <= previousTime) throw new Error("Replay timestamps are not strictly increasing");
    if (frame.coordinate_system !== expected.coordinateSystem) {
      throw new Error("Replay coordinate system does not match the manifest");
    }
    if (!Array.isArray(frame.vehicles) || !Array.isArray(frame.traffic_lights)) {
      throw new Error(`Replay arrays are invalid on line ${index + 1}`);
    }
    const vehicles = frame.vehicles.map((vehicle) => parseVehicle(vehicle, index + 1));
    const idsInFrame = new Set<string>();
    vehicles.forEach((vehicle) => {
      if (idsInFrame.has(vehicle.vehicle_id)) {
        throw new Error(`Replay duplicates vehicle ${vehicle.vehicle_id} on line ${index + 1}`);
      }
      idsInFrame.add(vehicle.vehicle_id);
      vehicleIds.add(vehicle.vehicle_id);
    });
    const trafficLights = frame.traffic_lights.map((light) => parseTrafficLight(light, index + 1));
    if (!trafficLights.some((light) => light.traffic_light_id === expected.trafficLightId)) {
      throw new Error(`Replay is missing ${expected.trafficLightId} on line ${index + 1}`);
    }
    let metrics: ReplayMetrics | undefined;
    if (frame.metrics !== undefined) {
      const source = objectValue(frame.metrics, `metrics on line ${index + 1}`);
      const waiting = finiteNumber(source.cumulative_waiting_time_s, "metrics.cumulative_waiting_time_s");
      if (waiting < 0 || (previousWaiting !== null && waiting < previousWaiting)) {
        throw new Error("Replay cumulative waiting time is negative or decreasing");
      }
      if (index === 0 && waiting !== 0) {
        throw new Error("Replay cumulative waiting time must begin at zero");
      }
      if (
        !Number.isInteger(source.active_vehicle_count) ||
        (source.active_vehicle_count as number) < 0 ||
        !Number.isInteger(source.arrived_vehicle_count) ||
        (source.arrived_vehicle_count as number) < 0 ||
        source.measurement !== "sum_waiting_vehicle_intervals_x_step_duration"
      ) {
        throw new Error(`Replay metrics are invalid on line ${index + 1}`);
      }
      metrics = {
        cumulative_waiting_time_s: waiting,
        active_vehicle_count: source.active_vehicle_count as number,
        arrived_vehicle_count: source.arrived_vehicle_count as number,
        measurement: "sum_waiting_vehicle_intervals_x_step_duration",
      };
      previousWaiting = waiting;
      waitingSamples += 1;
    }
    frames.push({
      schema_version: REPLAY_SCHEMA_VERSION,
      record_type: "frame",
      frame_index: index,
      simulation_time_s: time,
      coordinate_system: expected.coordinateSystem,
      vehicles,
      traffic_lights: trafficLights,
      ...(metrics ? { metrics } : {}),
    });
    previousTime = time;
  });
  if (expected.frameCount !== undefined && frames.length !== expected.frameCount) {
    throw new Error(`Replay frame count ${frames.length} does not match manifest ${expected.frameCount}`);
  }
  if (expected.durationS !== undefined && Math.abs(previousTime - expected.durationS) > 1e-6) {
    throw new Error(`Replay duration ${previousTime} does not match manifest ${expected.durationS}`);
  }
  if (waitingSamples !== 0 && waitingSamples !== frames.length) {
    throw new Error("Replay waiting-time series is incomplete");
  }
  return {
    frames,
    vehicleIds,
    durationS: previousTime,
    coordinateSystem: expected.coordinateSystem,
    waitingSeriesAvailable: waitingSamples === frames.length,
  };
}

const interpolateAngle = (from: number, to: number, progress: number) => {
  const delta = ((to - from + 540) % 360) - 180;
  return from + delta * progress;
};

export function frameAtTime(stream: ReplayStream, requestedTimeS: number): ReplayFrame {
  const time = clampTime(requestedTimeS, stream.durationS);
  let low = 0;
  let high = stream.frames.length - 1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (stream.frames[middle].simulation_time_s <= time) low = middle + 1;
    else high = middle - 1;
  }
  const previous = stream.frames[Math.max(0, high)];
  const next = stream.frames[Math.min(stream.frames.length - 1, high + 1)];
  if (previous === next || Math.abs(time - previous.simulation_time_s) < 1e-9) return previous;
  const span = next.simulation_time_s - previous.simulation_time_s;
  const progress = span > 0 ? (time - previous.simulation_time_s) / span : 0;
  const nextById = new Map(next.vehicles.map((vehicle) => [vehicle.vehicle_id, vehicle]));
  const vehicles = previous.vehicles.flatMap((source) => {
    const target = nextById.get(source.vehicle_id);
    if (!target) return [];
    return [{
      ...source,
      x_m: source.x_m + (target.x_m - source.x_m) * progress,
      y_m: source.y_m + (target.y_m - source.y_m) * progress,
      angle_deg: interpolateAngle(source.angle_deg, target.angle_deg, progress),
      speed_mps: source.speed_mps + (target.speed_mps - source.speed_mps) * progress,
      lane_id: progress < 0.5 ? source.lane_id : target.lane_id,
      edge_id: progress < 0.5 ? source.edge_id : target.edge_id,
    }];
  });
  return { ...previous, simulation_time_s: time, vehicles };
}

export function clampTime(timeS: number, durationS: number) {
  if (!Number.isFinite(timeS) || !Number.isFinite(durationS) || durationS < 0) return 0;
  return Math.min(durationS, Math.max(0, timeS));
}

export function advancePlayback(timeS: number, elapsedMs: number, speed: number, durationS: number) {
  return clampTime(timeS + Math.max(0, elapsedMs) * Math.max(0, speed) / 1000, durationS);
}

export function videoTimeAtReplayTime(replayTimeS: number, videoDurationS: number) {
  return clampTime(replayTimeS, videoDurationS);
}

export function replayMetricsAtTime(stream: ReplayStream, requestedTimeS: number) {
  return frameAtTime(stream, requestedTimeS).metrics ?? null;
}

export function sourceStatus(timeS: number, durationS: number, label: "video" | "simulation") {
  if (timeS >= durationS) return label === "video" ? "Video ended" : "Simulation finished";
  return "Playing";
}

export function replaySignalColor(state: string | undefined) {
  if (state === "G") return "#70f8a7";
  if (state === "g" || state === "s") return "#2ad083";
  if (state === "y" || state === "Y") return "#ffd15c";
  if (state === "r" || state === "R") return "#ff5964";
  if (state === "u") return "#f2994a";
  return "#667680";
}

export function switchVideoSource<T extends { source: VideoSource; timeS: number; playing: boolean }>(
  playback: T,
  source: VideoSource,
  available: boolean,
): T {
  if (!available) throw new Error("Selected video source is unavailable");
  return { ...playback, source };
}

export function validateReplayGeometry(manifest: ReplayManifest, geometry: NetworkGeometry) {
  if (
    manifest.schema_version !== REPLAY_SCHEMA_VERSION ||
    manifest.network_geometry.scenario_id !== "single_intersection" ||
    manifest.network_geometry.coordinate_system !== "synthetic_cartesian_metres" ||
    geometry.scenario_selection_id !== manifest.network_geometry.scenario_id ||
    geometry.coordinate_system !== manifest.network_geometry.coordinate_system
  ) {
    throw new Error("Replay manifest and network geometry are incompatible");
  }
  const adaptive = manifest.replays.gap_v1;
  if (
    manifest.replays.fixed.strategy !== "fixed" ||
    adaptive.strategy !== "gap_v1" ||
    adaptive.controller_provenance.selected_strategy !== "gap_v1" ||
    adaptive.controller_provenance.active_strategy_verified_at_runtime !== true ||
    adaptive.controller_provenance.active_traffic_light_ids.length !== 1 ||
    adaptive.controller_provenance.active_traffic_light_ids[0] !== "demo_01" ||
    adaptive.controller_provenance.validation_errors.length !== 0
  ) {
    throw new Error("Replay manifest does not prove gap_v1 activation at demo_01");
  }
}

export function isReplayDatasetId(value: unknown): value is ReplayDatasetId {
  return typeof value === "string" && (REPLAY_DATASET_IDS as readonly string[]).includes(value);
}

export function datasetManifestUrl(datasetId: ReplayDatasetId) {
  return `/api/operator/ai-traffic/datasets/${datasetId}/manifest`;
}

/** Strictly parse GET /api/ai-traffic/datasets; unknown dataset IDs are rejected. */
export function parseDatasetList(value: unknown): ReplayDatasetStatus[] {
  const body = objectValue(value, "dataset list");
  if (!Array.isArray(body.datasets)) throw new Error("Replay dataset list is invalid");
  const seen = new Set<string>();
  return body.datasets.map((raw) => {
    const item = objectValue(raw, "dataset entry");
    if (!isReplayDatasetId(item.dataset_id) || seen.has(item.dataset_id)) {
      throw new Error("Replay dataset list contains an unknown or duplicate dataset");
    }
    seen.add(item.dataset_id);
    if (typeof item.available !== "boolean" || !Array.isArray(item.video_sources)) {
      throw new Error("Replay dataset entry is invalid");
    }
    return {
      dataset_id: item.dataset_id,
      label: typeof item.label === "string" && item.label ? item.label : REPLAY_DATASET_LABELS[item.dataset_id],
      description: typeof item.description === "string" ? item.description : "",
      default: item.default === true,
      available: item.available,
      detail: typeof item.detail === "string" ? item.detail : null,
      video_sources: item.video_sources.filter((source): source is VideoSource =>
        (VIDEO_SOURCES as readonly unknown[]).includes(source)),
    };
  });
}

/** The manifest must belong to the dataset the page requested. */
export function assertManifestSelection(manifest: ReplayManifest, datasetId: ReplayDatasetId) {
  if (manifest.selection_id !== datasetId) {
    throw new Error(`Replay manifest belongs to ${manifest.selection_id ?? "an unknown dataset"}, not ${datasetId}`);
  }
}

export function availableVideoSources(manifest: ReplayManifest): VideoSource[] {
  return VIDEO_SOURCES.filter((source) => manifest.assets[source]?.available === true);
}

/** Prefer the AI-annotated video; never substitute one source for the other. */
export function defaultVideoSource(manifest: ReplayManifest): VideoSource | null {
  const available = availableVideoSources(manifest);
  if (available.includes("annotated_video")) return "annotated_video";
  return available[0] ?? null;
}

export function videoDurationFor(manifest: ReplayManifest, source: VideoSource): number | undefined {
  const value = source === "original_video" ? manifest.video.duration_s : manifest.video.annotated_duration_s;
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

/** True only when the manifest declares that no original footage exists. */
export function isAnnotatedOnly(manifest: ReplayManifest) {
  return manifest.video.source_kind === "annotated_only" || manifest.video.original_video_available === false;
}

/** The shared timeline spans the longer of the two recorded replays. */
export function replayTimelineDuration(fixed: ReplayStream, gap: ReplayStream) {
  return Math.max(fixed.durationS, gap.durationS);
}

/** Playback state every dataset switch starts from: paused at t = 0. */
export function initialPlayback() {
  return { timeS: 0, playing: false } as const;
}

/**
 * Monotonic request tokens. A response may update the page only while its token
 * is still the latest, so rapid dataset switching never shows stale data.
 */
export function createRequestSequencer() {
  let latest = 0;
  return {
    next: () => {
      latest += 1;
      return latest;
    },
    isCurrent: (token: number) => token === latest,
  };
}
