export type ServiceState = "idle" | "running" | "paused" | "finished" | "error";
export type NetworkId = "single_intersection" | "london";
export type TrafficProfile = "normal" | "rush_hour" | "unbalanced";
export type ControllerMode = "fixed_timing" | "adaptive_network" | "adaptive_emergency_priority";

export interface SimulationConfiguration {
  network: NetworkId;
  traffic_profile: TrafficProfile;
  controller_mode: ControllerMode;
  emergency_vehicles_enabled: boolean;
}

export interface ConfigurationOptions {
  networks: Array<{ id: NetworkId; display_name: string }>;
  traffic_profiles: Array<{ id: TrafficProfile; display_name: string }>;
  controller_modes: Array<{ id: ControllerMode; display_name: string }>;
  emergency_vehicle_options: Array<{ enabled: boolean; display_name: string }>;
}

export interface SimulationStatus {
  state: ServiceState;
  simulation_speed: number;
  active_configuration: SimulationConfiguration | null;
  network: NetworkId | null;
  traffic_profile: TrafficProfile | null;
  controller_mode: ControllerMode | null;
  emergency_vehicles_enabled: boolean | null;
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
  emergency_event_id?: string;
  emergency_vehicle_id?: string;
  intersection_id?: string;
  emergency_state?: string;
}

export interface EmergencyEvent {
  event_id: string;
  run_id: string;
  emergency_vehicle_id: string;
  vehicle_type: string;
  intersection_id: string;
  approach: string | null;
  first_seen_simulation_time_s: number;
  updated_simulation_time_s: number;
  state: "detected" | "priority_active" | "served" | "expired" | "completed";
  priority_supported: boolean;
  priority_reason: string | null;
}

export interface SimulationSnapshot {
  schema_version: string;
  scenario_id: string;
  scenario_selection_id?: string;
  run_id: string;
  active_configuration: SimulationConfiguration;
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
  emergency_events?: EmergencyEvent[];
  vehicles?: Vehicle[];
}

export type StreamEnvelope =
  | { type: "status"; data: SimulationStatus }
  | { type: "snapshot"; data: SimulationSnapshot };

/* ------------------------------------------------------------------ */
/* Analytics files (frontend/public/analytics/*.json), served via    */
/* GET /api/analytics. See DATA_CONTRACTS.md section O. null = unknown. */
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

/** One row of GET /api/analytics (the local SQLite copy of index.json + files). */
export interface AnalyticsListEntry {
  id: string;
  label: string;
  kind: AnalyticsKind;
  schema_version: string | null;
  loaded_at: string;
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

export function isAnalyticsList(value: unknown): value is AnalyticsListEntry[] {
  return Array.isArray(value) && value.every((entry) => isRecord(entry)
    && typeof entry.id === "string" && entry.id.length > 0
    && typeof entry.label === "string"
    && (entry.kind === "simulation" || entry.kind === "vision")
    && isNullableString(entry.schema_version)
    && typeof entry.loaded_at === "string");
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

/* ------------------------------------------------------------------ */
/* Recorded Live Simulation runs (SQLite `runs` table), served via    */
/* GET /api/analytics/runs/*. See DATA_CONTRACTS.md O.5. null = unknown. */
/* ------------------------------------------------------------------ */

export const RECORDED_RUN_STATUSES = ["finished", "stopped", "error"] as const;
const NETWORK_IDS: readonly NetworkId[] = ["single_intersection", "london"];
const TRAFFIC_PROFILES: readonly TrafficProfile[] = ["normal", "rush_hour", "unbalanced"];
const CONTROLLER_MODES: readonly ControllerMode[] = ["fixed_timing", "adaptive_network", "adaptive_emergency_priority"];
export type RecordedRunStatus = (typeof RECORDED_RUN_STATUSES)[number];

export interface RecordedRunInfo {
  run_id: string;
  scenario_id: string;
  legacy_scenario_id: string | null;
  /** Same value as controller_mode (the runs.control_mode column). */
  control_mode: ControllerMode;
  network: NetworkId;
  traffic_profile: TrafficProfile;
  controller_mode: ControllerMode;
  emergency_vehicles_enabled: boolean;
  status: RecordedRunStatus;
  started_at: string;
  ended_at: string;
  sim_start_s: number | null;
  sim_end_s: number | null;
  sim_duration_s: number | null;
  sample_count: number;
  error: string | null;
}

/** RunMetrics.snapshot() at the end of the run (section E). Time loss stays null in the live service. */
export interface RecordedRunSummary {
  total_waiting_time_s: number | null;
  average_waiting_time_s: number | null;
  departed_vehicle_count: number | null;
  arrived_vehicle_count: number | null;
  active_vehicle_count: number | null;
  network_queue_vehicles: number | null;
  maximum_network_queue_vehicles: number | null;
  total_time_loss_s: number | null;
  average_time_loss_s: number | null;
  [key: string]: unknown;
}

export const RECORDED_RUN_SUMMARY_KEYS = [
  "total_waiting_time_s", "average_waiting_time_s", "departed_vehicle_count", "arrived_vehicle_count",
  "active_vehicle_count", "network_queue_vehicles", "maximum_network_queue_vehicles",
  "total_time_loss_s", "average_time_loss_s",
] as const;

export interface RecordedRunSample {
  t_s: number | null;
  network_queue_vehicles: number | null;
  active_vehicle_count: number | null;
  departed_cumulative: number | null;
  arrived_cumulative: number | null;
  queue_by_traffic_light: Record<string, number | null>;
  queue_by_approach: Record<string, number | null>;
  phase_by_traffic_light: Record<string, { phase_index: number | null; phase_id: string | null }>;
}

export interface RecordedRunIntersection {
  traffic_light_id: string;
  mean_queue_vehicles: number | null;
  max_queue_vehicles: number | null;
  sample_count: number;
}

export interface RecordedRunPhase {
  traffic_light_id: string;
  phase_change_count: number;
  completed_green_phases: number;
  mean_green_duration_s: number | null;
}

export interface RecordedRun {
  schema_version: string;
  kind: "simulation_run";
  run: RecordedRunInfo;
  summary: RecordedRunSummary | null;
  timeseries: { interval_s: number; queue_measurement: string; samples: RecordedRunSample[] };
  intersections: RecordedRunIntersection[];
  phases: RecordedRunPhase[];
}

export interface RecordedRunPair {
  /** Resolved scenario id, with "_emergency" when emergency vehicles were enabled. */
  scenario_id: string;
  fixed: RecordedRun | null;
  adaptive: RecordedRun | null;
}

function isRecordedRunInfo(value: unknown): value is RecordedRunInfo {
  return isRecord(value)
    && typeof value.run_id === "string"
    && typeof value.scenario_id === "string"
    && isNullableString(value.legacy_scenario_id)
    && (CONTROLLER_MODES as readonly unknown[]).includes(value.control_mode)
    && (NETWORK_IDS as readonly unknown[]).includes(value.network)
    && (TRAFFIC_PROFILES as readonly unknown[]).includes(value.traffic_profile)
    && (CONTROLLER_MODES as readonly unknown[]).includes(value.controller_mode)
    && typeof value.emergency_vehicles_enabled === "boolean"
    && (RECORDED_RUN_STATUSES as readonly unknown[]).includes(value.status)
    && typeof value.started_at === "string"
    && typeof value.ended_at === "string"
    && isNullableNumber(value.sim_start_s)
    && isNullableNumber(value.sim_end_s)
    && isNullableNumber(value.sim_duration_s)
    && isNumber(value.sample_count)
    && isNullableString(value.error);
}

function isRecordedRunSummary(value: unknown): value is RecordedRunSummary {
  return isRecord(value) && RECORDED_RUN_SUMMARY_KEYS.every((key) => isNullableNumber(value[key]));
}

function isRecordedRunSample(value: unknown): value is RecordedRunSample {
  return isRecord(value)
    && isNullableNumber(value.t_s)
    && isNullableNumber(value.network_queue_vehicles)
    && isNullableNumber(value.active_vehicle_count)
    && isNullableNumber(value.departed_cumulative)
    && isNullableNumber(value.arrived_cumulative)
    && isRecordOf(value.queue_by_traffic_light, isNullableNumber)
    && isRecordOf(value.queue_by_approach, isNullableNumber)
    && isRecordOf(value.phase_by_traffic_light, (item): item is RecordedRunSample["phase_by_traffic_light"][string] =>
      isRecord(item) && isNullableNumber(item.phase_index) && isNullableString(item.phase_id));
}

export function isRecordedRun(value: unknown): value is RecordedRun {
  if (!isRecord(value) || value.kind !== "simulation_run" || typeof value.schema_version !== "string") return false;
  const { timeseries } = value;
  return isRecordedRunInfo(value.run)
    && (value.summary === null || isRecordedRunSummary(value.summary))
    && isRecord(timeseries)
    && isNumber(timeseries.interval_s)
    && typeof timeseries.queue_measurement === "string"
    && Array.isArray(timeseries.samples) && timeseries.samples.every(isRecordedRunSample)
    && Array.isArray(value.intersections) && value.intersections.every((item: unknown) => isRecord(item)
      && typeof item.traffic_light_id === "string" && isNullableNumber(item.mean_queue_vehicles)
      && isNullableNumber(item.max_queue_vehicles) && isNumber(item.sample_count))
    && Array.isArray(value.phases) && value.phases.every((item: unknown) => isRecord(item)
      && typeof item.traffic_light_id === "string" && isNumber(item.phase_change_count)
      && isNumber(item.completed_green_phases) && isNullableNumber(item.mean_green_duration_s));
}

export function isRecordedRunPair(value: unknown): value is RecordedRunPair {
  return isRecord(value)
    && typeof value.scenario_id === "string"
    && (value.fixed === null || isRecordedRun(value.fixed))
    && (value.adaptive === null || isRecordedRun(value.adaptive));
}
