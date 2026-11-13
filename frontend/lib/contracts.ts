export type ServiceState = "idle" | "running" | "paused" | "finished" | "error";

export interface SimulationStatus {
  state: ServiceState;
  simulation_speed: number;
  simulation_time_s: number | null;
  has_snapshot: boolean;
  error: string | null;
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
  coordinate_system: string;
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
  traffic_lights: Array<{ traffic_light_id: string }>;
  controlled_links: Array<{
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
  x_m: number;
  y_m: number;
  angle_deg: number;
  speed_mps: number;
  road_id: string;
}

export interface QueueValue { vehicles: number; measurement: string }

export interface SimulationSnapshot {
  schema_version: string;
  scenario_id: string;
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
  vehicles?: Vehicle[];
}

export type StreamEnvelope =
  | { type: "status"; data: SimulationStatus }
  | { type: "snapshot"; data: SimulationSnapshot };
