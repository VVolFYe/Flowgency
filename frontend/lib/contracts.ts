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
    traffic_light_ids: string[];
    last_cycle_decision: {
      intersection_id: string;
      queues: Record<string, number>;
      green_durations_s: Record<string, number>;
      reason: string;
    } | null;
  };
  emergency_priority?: {
    active_vehicle_id: string | null;
    active_approach: string | null;
    reason: string | null;
  };
  vehicles?: Vehicle[];
}

export type StreamEnvelope =
  | { type: "status"; data: SimulationStatus }
  | { type: "snapshot"; data: SimulationSnapshot };
