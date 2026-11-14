export type ServiceState = "idle" | "running" | "paused" | "finished" | "error";

export interface SimulationStatus {
  state: ServiceState;
  simulation_speed: number;
  control_mode?: "fixed" | "adaptive" | "adaptive_with_emergency_priority";
  scenario_id: string;
  simulation_time_s: number | null;
  has_snapshot: boolean;
  error: string | null;
}

export interface RunMetrics {
  total_waiting_time_s: number;
  average_waiting_time_s: number | null;
  average_waiting_time_denominator: "departed_vehicle_count";
  departed_vehicle_count: number;
  arrived_vehicle_count: number;
  active_vehicle_count: number;
  network_queue_vehicles: number;
  maximum_network_queue_vehicles: number;
  total_time_loss_s: number | null;
  average_time_loss_s: number | null;
  time_loss_status: string;
  waiting_time_measurement: string;
}

export interface ScenarioCandidate {
  junction_id: string;
  traffic_light_id: string | null;
  incoming_edges: string[];
}

export interface ScenarioTargetMapping {
  intersection_id: string;
  target_location: string;
  jamcam_id: string;
  mapping_status: string;
  latitude: number;
  longitude: number;
  candidates: ScenarioCandidate[];
}

export interface SimulationScenario {
  scenario_id: string;
  display_name: string;
  description: string;
  coordinate_system: string;
  supports_adaptive_control: boolean;
  supports_emergency_priority?: boolean;
  default_control_mode?: "fixed" | "adaptive" | "adaptive_with_emergency_priority";
  known_limitation: string | null;
  target_mappings: ScenarioTargetMapping[];
}

export interface Point { x_m: number; y_m: number }

export interface Lane {
  lane_id: string;
  index: number;
  speed_limit_mps: number;
  length_m: number;
  width_m: number;
  shape: Point[];
}

export interface NetworkGeometry {
  schema_version: string;
  scenario_id: string;
  scenario_selection_id: string;
  coordinate_system: string;
  projection?: {
    proj_parameter: string | null;
    net_offset: string | null;
    original_boundary: string | null;
  };
  rendering?: { invert_y_axis_for_screen: boolean };
  bounds: { min_x_m: number; min_y_m: number; max_x_m: number; max_y_m: number };
  edges: Array<{
    edge_id: string;
    from_junction_id: string;
    to_junction_id: string;
    function: string;
    is_internal: boolean;
    lanes: Lane[];
  }>;
  junctions: Array<{
    junction_id: string;
    type: string;
    x_m: number;
    y_m: number;
    shape: Point[];
  }>;
  traffic_lights: Array<{
    traffic_light_id: string;
    junctions?: Array<{ junction_id: string; x_m: number; y_m: number }>;
  }>;
  controlled_links: Array<{
    traffic_light_id?: string;
    link_index: number;
    approach: string;
    from_lane: string;
    to_lane: string;
    movement: string;
  }>;
}

export interface Vehicle {
  vehicle_id: string;
  vehicle_type: string;
  is_emergency?: boolean;
  x_m: number;
  y_m: number;
  angle_deg: number;
  speed_mps: number;
  road_id: string;
  lane_id?: string;
}

export interface QueueValue { vehicles: number; measurement: string }

export interface VoiceAlert {
  event_id: string;
  run_id: string;
  message_id: string;
  text: string;
  language: "en" | "ro";
  simulation_time_s: number;
  priority: "emergency" | "routine";
}

export interface SimulationSnapshot {
  schema_version: string;
  scenario_id: string;
  scenario_selection_id?: string;
  run_id: string;
  intersection_id: string;
  simulation_time_s: number;
  traffic_light_id?: string | null;
  current_phase_index?: number | null;
  current_phase_id: string | null;
  remaining_phase_duration_s: number | null;
  queue_lengths_by_approach: Record<string, QueueValue | null>;
  traffic_light_state: string | null;
  coordinate_system?: string | null;
  traffic_light_controllers?: Record<string, {
    traffic_light_id: string;
    current_phase_index: number;
    current_phase_id: string;
    remaining_phase_duration_s: number;
    traffic_light_state: string;
    queue_lengths_by_lane: Record<string, QueueValue>;
    total_queue_vehicles: number;
  }>;
  network_queue?: QueueValue & { controlled_lane_count?: number };
  metrics?: RunMetrics;
  adaptive_control?: {
    scope: string;
    active_controller_count?: number;
    traffic_light_ids: string[];
    fixed_controller_count?: number;
    fixed_controllers?: Record<string, string>;
    last_cycle_decision: {
      intersection_id: string;
      traffic_light_id?: string;
      strategy?: string;
      queues: Record<string, number>;
      demand_scores?: Record<string, number> | null;
      green_durations_s: Record<string, number>;
      reason: string;
    } | null;
    last_cycle_decisions?: Record<string, {
      intersection_id: string;
      traffic_light_id?: string;
      strategy?: string;
      queues: Record<string, number>;
      demand_scores?: Record<string, number> | null;
      green_durations_s: Record<string, number>;
      reason: string;
    }>;
  };
  emergency_priority?: {
    active_vehicle_id: string | null;
    active_approach: string | null;
    reason: string | null;
  };
  voice_alerts?: VoiceAlert[];
  vehicles?: Vehicle[];
}

export type StreamEnvelope =
  | { type: "status"; data: SimulationStatus }
  | { type: "snapshot"; data: SimulationSnapshot };

/* ------------------------------------------------------------------ */
/* Static analytics files (frontend/public/analytics/*.json).         */
/* See docs/DATA_CONTRACTS.md section K. null always means unknown.   */
/* ------------------------------------------------------------------ */

export type AnalyticsKind = "simulation" | "vision";
export type ComparisonMode = "fixed" | "adaptive";
export const COMPARISON_MODES: readonly ComparisonMode[] = ["fixed", "adaptive"];

export interface AnalyticsIndexEntry {
  id: string;
  label: string;
  kind: AnalyticsKind;
  file: string;
}

export interface PairedMetric {
  fixed: number | null;
  adaptive: number | null;
  absolute_improvement: number | null;
  percentage_improvement: number | null;
  better: "lower" | "higher";
}

export const SIMULATION_SUMMARY_KEYS = [
  "total_waiting_time_s",
  "average_waiting_time_s",
  "total_time_loss_s",
  "average_time_loss_s",
  "average_trip_duration_s",
  "throughput_vehicles_per_hour",
  "mean_network_queue_vehicles",
  "max_network_queue_vehicles",
] as const;
export type SimulationSummaryKey = (typeof SIMULATION_SUMMARY_KEYS)[number];

export const SIMULATION_DISTRIBUTION_KEYS = ["waiting_time_s", "time_loss_s", "trip_duration_s"] as const;
export type SimulationDistributionKey = (typeof SIMULATION_DISTRIBUTION_KEYS)[number];

export interface TimeseriesSample {
  t_s: number;
  network_queue_vehicles: number;
  active_vehicles: number;
  arrived_cumulative: number;
}

export interface ModeDistribution {
  count: number;
  p50: number | null;
  p90: number | null;
  p95: number | null;
  max: number | null;
  histogram: number[];
}

export interface IntersectionStats {
  mean_queue: number | null;
  max_queue: number | null;
  mean_green_s: number | null;
  completed_green_phases: number;
  decision_count: number | null;
}

export interface EmergencyStats {
  emergency_trip_count: number;
  normal_trip_count: number;
  emergency_average_time_loss_s: number | null;
  normal_average_time_loss_s: number | null;
}

export interface AnalyticsRunValidation {
  passed: boolean;
  errors: string[];
  departed: number | null;
  arrived: number | null;
  completed: number | null;
  unfinished: number | null;
  duplicate_tripinfo_ids: number | null;
  collisions: number | null;
  teleports: number | null;
  process_exit_code: number | null;
  terminated_by_step_limit: boolean | null;
}

export interface SimulationAnalytics {
  schema_version: "1.0";
  kind: "simulation";
  scenario_id: string;
  scenario_name: string;
  provenance: {
    authoritative_report: string | null;
    config: string | null;
    network: string | null;
    routes: string;
    adaptive_manifest: string | null;
    seed: number | null;
    expected_vehicle_count: number;
    expected_vehicle_ids_sha256: string;
    snapshot_created_on: string;
  };
  experiment: {
    fixed_label: string;
    adaptive_label: string;
    adaptive_scope: string;
    controlled_difference: string;
    adaptive_controller_count: number | null;
  };
  runs: Record<ComparisonMode, { steps: number | null; cycle_decisions: number | null }>;
  summary: Record<SimulationSummaryKey, PairedMetric>;
  timeseries: { interval_s: number; queue_measurement: string } & Record<ComparisonMode, TimeseriesSample[] | null>;
  distributions: Record<SimulationDistributionKey, { bin_edges: number[] | null } & Record<ComparisonMode, ModeDistribution | null>>;
  intersections: { queue_measurement: string } & Record<ComparisonMode, Record<string, IntersectionStats> | null>;
  emergency: ({ vehicle_types: string[] } & Record<ComparisonMode, EmergencyStats | null>) | null;
  validation: {
    passed: boolean;
    matched_vehicle_count: number | null;
    errors: string[];
  } & Record<ComparisonMode, AnalyticsRunValidation>;
  limitations: string[];
}

export interface FlowWindow {
  start_s: number;
  end_s: number;
  partial: boolean;
  entered: Record<string, number | null>;
  discharged: Record<string, number | null>;
}

export interface VisionAnalytics {
  schema_version: "1.0";
  kind: "vision";
  source: {
    label: string;
    duration_s: number;
    duration_definition: string;
    fps: number | null;
    model_id: string;
    sample_readme: string | null;
    counts_path: string;
    events_path: string;
    video_in_repository: boolean;
  };
  arms: string[];
  timeseries: {
    t_s: number[];
    vehicles_on_approach: Record<string, Array<number | null>>;
    in_intersection: Array<number | null>;
  };
  flow_per_minute: FlowWindow[];
  totals: Record<string, { entered: number | null; discharged: number | null; peak_vehicles_on_approach: number | null }>;
  turning_matrix: {
    origins: string[];
    exits: string[];
    counts: Record<string, Record<string, number>>;
    total_exits: number;
    unknown_origin_exits: number;
  };
  limitations: string[];
}

export type AnalyticsDocument = SimulationAnalytics | VisionAnalytics;

/* Runtime guards: static files are checked before rendering, like the benchmark page. */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || isNumber(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isNumberArray(value: unknown, nullable = false): boolean {
  return Array.isArray(value) && value.every((item) => (nullable ? isNullableNumber(item) : isNumber(item)));
}

function isRecordOf<T>(value: unknown, guard: (item: unknown) => item is T): value is Record<string, T> {
  return isRecord(value) && Object.values(value).every(guard);
}

function hasModes<T>(value: Record<string, unknown>, guard: (item: unknown) => boolean): value is Record<string, unknown> & Record<ComparisonMode, T> {
  return COMPARISON_MODES.every((mode) => guard(value[mode]));
}

const SAFE_ANALYTICS_FILE = /^[A-Za-z0-9_.-]+\.json$/;

export function isAnalyticsIndex(value: unknown): value is AnalyticsIndexEntry[] {
  return Array.isArray(value) && value.every((entry) => isRecord(entry)
    && typeof entry.id === "string" && entry.id.length > 0
    && typeof entry.label === "string"
    && (entry.kind === "simulation" || entry.kind === "vision")
    && typeof entry.file === "string" && SAFE_ANALYTICS_FILE.test(entry.file));
}

function isPairedMetric(value: unknown): value is PairedMetric {
  return isRecord(value)
    && isNullableNumber(value.fixed)
    && isNullableNumber(value.adaptive)
    && isNullableNumber(value.absolute_improvement)
    && isNullableNumber(value.percentage_improvement)
    && (value.better === "lower" || value.better === "higher");
}

function isTimeseriesSample(value: unknown): value is TimeseriesSample {
  return isRecord(value) && ["t_s", "network_queue_vehicles", "active_vehicles", "arrived_cumulative"].every((key) => isNumber(value[key]));
}

function isModeDistribution(value: unknown): value is ModeDistribution {
  return isRecord(value) && isNumber(value.count)
    && ["p50", "p90", "p95", "max"].every((key) => isNullableNumber(value[key]))
    && isNumberArray(value.histogram);
}

function isIntersectionStats(value: unknown): value is IntersectionStats {
  return isRecord(value)
    && isNullableNumber(value.mean_queue)
    && isNullableNumber(value.max_queue)
    && isNullableNumber(value.mean_green_s)
    && isNumber(value.completed_green_phases)
    && isNullableNumber(value.decision_count);
}

function isEmergencyStats(value: unknown): value is EmergencyStats {
  return isRecord(value)
    && isNumber(value.emergency_trip_count)
    && isNumber(value.normal_trip_count)
    && isNullableNumber(value.emergency_average_time_loss_s)
    && isNullableNumber(value.normal_average_time_loss_s);
}

function isAnalyticsRunValidation(value: unknown): value is AnalyticsRunValidation {
  return isRecord(value) && typeof value.passed === "boolean" && isStringArray(value.errors)
    && ["departed", "arrived", "completed", "unfinished", "duplicate_tripinfo_ids", "collisions", "teleports", "process_exit_code"]
      .every((key) => isNullableNumber(value[key]))
    && (value.terminated_by_step_limit === null || typeof value.terminated_by_step_limit === "boolean");
}

export function isSimulationAnalytics(value: unknown): value is SimulationAnalytics {
  if (!isRecord(value) || value.schema_version !== "1.0" || value.kind !== "simulation") return false;
  const { provenance, experiment, runs, summary, timeseries, distributions, intersections, emergency, validation } = value;
  if (![provenance, experiment, runs, summary, timeseries, distributions, intersections, validation].every(isRecord)) return false;
  const p = provenance as Record<string, unknown>;
  const e = experiment as Record<string, unknown>;
  const r = runs as Record<string, unknown>;
  const s = summary as Record<string, unknown>;
  const t = timeseries as Record<string, unknown>;
  const d = distributions as Record<string, unknown>;
  const i = intersections as Record<string, unknown>;
  const v = validation as Record<string, unknown>;
  return typeof value.scenario_id === "string"
    && typeof value.scenario_name === "string"
    && ["authoritative_report", "config", "network", "adaptive_manifest"].every((key) => isNullableString(p[key]))
    && typeof p.routes === "string"
    && isNullableNumber(p.seed)
    && isNumber(p.expected_vehicle_count)
    && typeof p.snapshot_created_on === "string"
    && ["fixed_label", "adaptive_label", "adaptive_scope", "controlled_difference"].every((key) => typeof e[key] === "string")
    && isNullableNumber(e.adaptive_controller_count)
    && hasModes(r, (run) => isRecord(run) && isNullableNumber(run.steps) && isNullableNumber(run.cycle_decisions))
    && SIMULATION_SUMMARY_KEYS.every((key) => isPairedMetric(s[key]))
    && isNumber(t.interval_s)
    && hasModes(t, (series) => series === null || (Array.isArray(series) && series.every(isTimeseriesSample)))
    && SIMULATION_DISTRIBUTION_KEYS.every((key) => {
      const item = d[key];
      return isRecord(item)
        && (item.bin_edges === null || isNumberArray(item.bin_edges))
        && hasModes(item, (mode) => mode === null || isModeDistribution(mode));
    })
    && hasModes(i, (mode) => mode === null || isRecordOf(mode, isIntersectionStats))
    && (emergency === null || (isRecord(emergency) && isStringArray(emergency.vehicle_types)
      && hasModes(emergency, (mode) => mode === null || isEmergencyStats(mode))))
    && typeof v.passed === "boolean"
    && isNullableNumber(v.matched_vehicle_count)
    && isStringArray(v.errors)
    && hasModes(v, isAnalyticsRunValidation)
    && isStringArray(value.limitations);
}

function isFlowWindow(value: unknown): value is FlowWindow {
  return isRecord(value) && isNumber(value.start_s) && isNumber(value.end_s) && typeof value.partial === "boolean"
    && isRecordOf(value.entered, isNullableNumber) && isRecordOf(value.discharged, isNullableNumber);
}

export function isVisionAnalytics(value: unknown): value is VisionAnalytics {
  if (!isRecord(value) || value.schema_version !== "1.0" || value.kind !== "vision") return false;
  const { source, timeseries, totals, turning_matrix: matrix } = value;
  if (!isRecord(source) || !isRecord(timeseries) || !isRecord(totals) || !isRecord(matrix)) return false;
  const length = Array.isArray(timeseries.t_s) ? timeseries.t_s.length : -1;
  const sameLength = (series: unknown) => isNumberArray(series, true) && (series as unknown[]).length === length;
  return typeof source.label === "string"
    && isNumber(source.duration_s)
    && isNullableNumber(source.fps)
    && typeof source.model_id === "string"
    && isNullableString(source.sample_readme)
    && isStringArray(value.arms)
    && isNumberArray(timeseries.t_s)
    && isRecordOf(timeseries.vehicles_on_approach, (series): series is Array<number | null> => sameLength(series))
    && sameLength(timeseries.in_intersection)
    && Array.isArray(value.flow_per_minute) && value.flow_per_minute.every(isFlowWindow)
    && isRecordOf(totals, (item): item is VisionAnalytics["totals"][string] => isRecord(item)
      && isNullableNumber(item.entered) && isNullableNumber(item.discharged) && isNullableNumber(item.peak_vehicles_on_approach))
    && isStringArray(matrix.origins)
    && isStringArray(matrix.exits)
    && isRecordOf(matrix.counts, (row): row is Record<string, number> => isRecordOf(row, isNumber))
    && isNumber(matrix.total_exits)
    && isNumber(matrix.unknown_origin_exits)
    && isStringArray(value.limitations);
}

export function isAnalyticsDocument(value: unknown, kind: AnalyticsKind): value is AnalyticsDocument {
  return kind === "simulation" ? isSimulationAnalytics(value) : isVisionAnalytics(value);
}
