# Data contracts

These are versioned design contracts, not implemented endpoints. JSON uses `snake_case`, ISO 8601 UTC wall-clock timestamps, seconds for durations, metres for positions, and stable project IDs. Top-level payloads carry `schema_version`; examples begin at `1.0`.

## Shared semantics

- Omit an optional field or use `null` when unknown; never silently substitute zero.
- Zero means a producer measured or computed a value and found none.
- Approach keys are scenario-defined IDs mapped separately to camera regions and SUMO lanes.
- Observation time is wall-clock time; simulation time is elapsed scenario time.
- Producers reject negative counts/durations and document coordinate reference systems.

An **observed vehicle count** is camera evidence from a window. **Estimated demand** (a future contract) is an inferred flow/rate or generated trip input. A **simulated queue length** is SUMO state. These retain distinct names and provenance.

## A. AI traffic observation

Only evaluated approaches appear in `vehicle_counts_by_approach`; an empty map does not imply zero traffic everywhere.

```json
{
  "schema_version": "1.0",
  "intersection_id": "J1",
  "camera_id": "JamCams_00001.04503",
  "observed_at": "2026-11-13T13:00:10Z",
  "window_duration_s": 10.0,
  "visible_approaches": ["southbound_in", "eastbound_in"],
  "vehicle_counts_by_approach": {
    "southbound_in": {"car": 12, "bus": 1, "bicycle": 2, "total": 15},
    "eastbound_in": {"car": 0, "total": 0}
  },
  "emergency_detections": [
    {
      "tracking_id": "track-847",
      "approach": "southbound_in",
      "vehicle_type": "ambulance",
      "active_lights_detected": true,
      "confidence": 0.91
    }
  ],
  "source": "recorded_video",
  "model_id": "yolo11-placeholder",
  "confidence": 0.88
}
```

Counts are non-negative integers. Confidence is in `[0, 1]`; model IDs are provenance, not instructions to consumers.

## B. SUMO intersection state

```json
{
  "schema_version": "1.0",
  "scenario_id": "single-intersection-v1",
  "scenario_selection_id": "single_intersection",
  "run_id": "run-20261113-001",
  "intersection_id": "J1",
  "simulation_time_s": 42.0,
  "traffic_light_id": "sumo_tls_01",
  "current_phase_index": 0,
  "current_phase_id": "vehicle_ns_green",
  "remaining_phase_duration_s": 8.0,
  "queue_lengths_by_approach": {
    "northbound_in": {"vehicles": 7, "measurement": "sumo_halting_number"},
    "southbound_in": {"vehicles": 3, "measurement": "sumo_halting_number"}
  },
  "traffic_light_state": "GGrr",
  "coordinate_system": "sumo_cartesian_metres",
  "vehicles": [
    {
      "vehicle_id": "veh-12",
      "vehicle_type": "passenger",
      "is_emergency": false,
      "x_m": 513.2,
      "y_m": 204.8,
      "angle_deg": 178.0,
      "speed_mps": 4.2,
      "road_id": "edge_s_in",
      "lane_id": "edge_s_in_0"
    }
  ]
}
```

Remaining duration may be `null`. `traffic_light_id`, `current_phase_index`, and `coordinate_system` are optional additive fields introduced for simulation integration and browser rendering; existing 1.0 consumers may ignore them. `current_phase_id` is the configured human-readable SUMO phase name when available. The SUMO link-state string requires separately versioned link-index metadata; clients must not infer movements from character position alone. Vehicle snapshots may be omitted from controller-only messages.

`scenario_id` keeps its established network-contract meaning (`single-intersection-v1` or `london-oval-kennington-v1`). The additive `scenario_selection_id` is the public registry choice used by the start API. Multi-intersection snapshots add `traffic_light_controllers`, keyed by every TraCI-enumerated controller ID. Each entry includes phase index/name, state, remaining duration, unique controlled-lane queues, and a per-controller total. `network_queue` sums each controlled lane once across controllers using measurement `sumo_halting_number_unique_controlled_lanes`. The legacy single-controller fields stay populated for the synthetic scenario and are `null`/empty for London.

Snapshots also include additive run-level `metrics`. `total_waiting_time_s` is accumulated once per simulation step as the number of active vehicles whose SUMO `getWaitingTime` is positive multiplied by that step's simulation-time duration. SUMO excludes intentional `<stop>` stages from this waiting state. The accumulator survives vehicle arrival and never uses the rolling-window `getAccumulatedWaitingTime`. `average_waiting_time_s` divides the total by `departed_vehicle_count`, so its denominator includes both active and completed vehicles; it is `null` before the first departure. `network_queue_vehicles` is the current deduplicated controlled-lane halt count, while `maximum_network_queue_vehicles` is the run maximum. Live time-loss fields remain `null` and explicitly defer to completed tripinfo output.

An adaptive London snapshot may include `adaptive_control`, identifying only the configured controller IDs and the latest cycle-boundary queues and green allocation. It does not imply that every network controller is adaptive.

For the synthetic scenario in adaptive mode, snapshots may additionally contain `control_reason`, a short machine-readable explanation such as `minimum_green_protected`, `hold_green_and_reevaluate`, `sustained_opposing_queue_advantage`, `opposing_approach_anti_starvation`, or `maximum_green_reached`. It is `null` before the first policy evaluation. This field describes the latest duration request, not a guarantee that a different phase has already begun. Fixed mode omits it.

The synthetic emergency mode adds `hold_compatible_green_for_emergency`, `minimum_green_protected_before_emergency`, and `request_normal_clearance_for_emergency` reasons, plus `emergency_priority` with nullable `active_vehicle_id`, `active_approach`, and `reason`. Vehicle snapshots include `is_emergency`, derived from declared SUMO type IDs `ambulance`, `fire_brigade`, and `police`; it is not a YOLO inference.

## C. Controller decision

```json
{
  "schema_version": "1.0",
  "decision_id": "decision-0042",
  "intersection_id": "J1",
  "simulation_time_s": 42.0,
  "target_phase_id": "vehicle_ns_green",
  "green_duration_s": 18.0,
  "reason": "north_south_congestion_score_highest_within_green_bounds",
  "emergency_priority": {
    "state": "inactive",
    "active_event_id": null,
    "queued_event_ids": []
  }
}
```

`target_phase_id` names a scenario-defined safe phase, not an arbitrary light string. Duration may be `null` for a transition request. The configured state machine and simulation adapter validate safety transitions.

## D. Emergency event

```json
{
  "schema_version": "1.0",
  "event_id": "emergency-J1-track-847-001",
  "tracking_id": "track-847",
  "intersection_id": "J1",
  "approach": "southbound_in",
  "vehicle_type": "ambulance",
  "detection_confidence": 0.91,
  "event_timestamp": "2026-11-13T13:00:10Z",
  "status": "active",
  "expires_at": "2026-11-13T13:00:25Z"
}
```

Statuses are `detected`, `active`, `served`, `expired`, and `cancelled`. Proposed deterministic ordering preserves an already compatible active request, then sorts eligible requests by `event_timestamp` and `event_id`.

## E. Simulation metrics

```json
{
  "schema_version": "1.0",
  "scenario_id": "single-intersection-v1",
  "run_id": "run-20261113-001",
  "control_mode": "adaptive_with_emergency_priority",
  "simulation_duration_s": 900.0,
  "average_waiting_time_s": 21.4,
  "queue_metrics": {
    "mean_queue_vehicles": 5.2,
    "max_queue_vehicles": 17,
    "measurement": "sumo_halting_number"
  },
  "throughput_vehicles": 438,
  "emergency_travel_delay_s": 6.8,
  "completed_trips": 421,
  "unfinished_trips": 17
}
```

Initial modes are `fixed`, `adaptive`, and `adaptive_with_emergency_priority`. Definitions and aggregation windows stay identical across comparisons. Emergency delay is `null` if no emergency trip exists. Completed and unfinished trips are explicit because arrival-only output can bias short runs.

## Versioning changes

Additive optional fields may remain minor-compatible; renamed/removed fields and semantic or unit changes require a new major version. Update this document, shared models, fixtures, producers, and consumers together. Support only agreed versions during the hackathon rather than building general negotiation.

## F. Simulation service status and stream envelope

The service status is transport metadata, not SUMO intersection state:

```json
{
  "state": "running",
  "simulation_speed": 4.0,
  "control_mode": "fixed",
  "scenario_id": "single_intersection",
  "simulation_time_s": 42.0,
  "has_snapshot": true,
  "error": null
}
```

`state` is one of `idle`, `running`, `paused`, `finished`, or `error`. Simulation speed is simulated seconds per wall-clock second. Time is `null` before the first run; `error` is populated only when the worker fails.

Status also carries `control_mode`: `fixed`, `adaptive`, or `adaptive_with_emergency_priority`. It defaults to `fixed` before a run and after stop. Emergency priority is available only on the verified synthetic mapping. It preserves the normal 10-second minimum on a conflicting green and the installed yellow/all-red sequence. A compatible green can extend beyond the normal 45-second maximum while the emergency vehicle remains on the incoming edge or inside the junction. This is simulation behavior, not a validated road-signal policy.

Status `scenario_id` is the active public selection ID. While idle, and after Stop, it is `single_intersection`. Reset retains the active selection.

WebSocket messages use a small envelope so status notifications and unchanged version 1.0 state snapshots can share one stream:

```json
{
  "type": "snapshot",
  "data": {
    "schema_version": "1.0",
    "scenario_id": "single-intersection-v1"
  }
}
```

`type` is currently `status` or `snapshot`. For `snapshot`, `data` is the complete SUMO intersection state contract rather than the abbreviated example above.

## G. Static SUMO network geometry

`GET /api/simulation/network` returns cached geometry parsed from the scenario network without starting SUMO or using TraCI:

```json
{
  "schema_version": "1.0",
  "scenario_id": "single-intersection-v1",
  "scenario_selection_id": "single_intersection",
  "coordinate_system": "synthetic_cartesian_metres",
  "bounds": {
    "min_x_m": 0.0,
    "min_y_m": 0.0,
    "max_x_m": 300.0,
    "max_y_m": 300.0
  },
  "edges": [
    {
      "edge_id": "east_in",
      "from_junction_id": "east",
      "to_junction_id": "demo_01",
      "function": "normal",
      "is_internal": false,
      "lanes": [
        {
          "lane_id": "east_in_0",
          "index": 0,
          "speed_limit_mps": 13.89,
          "length_m": 142.8,
          "width_m": 3.2,
          "shape": [
            {"x_m": 300.0, "y_m": 148.4},
            {"x_m": 157.2, "y_m": 148.4}
          ]
        }
      ]
    }
  ],
  "junctions": [
    {
      "junction_id": "demo_01",
      "type": "traffic_light",
      "x_m": 150.0,
      "y_m": 150.0,
      "shape": [{"x_m": 146.8, "y_m": 142.8}]
    }
  ],
  "traffic_lights": [{"traffic_light_id": "demo_01"}],
  "controlled_links": [
    {
      "link_index": 0,
      "approach": "northbound_in",
      "from_lane": "south_in_0",
      "to_lane": "north_out_0",
      "movement": "straight"
    }
  ]
}
```

All positions and shapes preserve SUMO Cartesian coordinates in metres. Internal edges use IDs beginning with `:` and are included so vehicles remain renderable while crossing the junction. A browser must apply the same scale and translation to geometry and live vehicle positions. If rendering onto a surface whose Y axis points downward, invert Y at presentation time; do not alter or relabel the API values as geographic coordinates.

Geometry also includes `projection` (`proj_parameter`, `net_offset`, and `original_boundary`) read from the actual `net.xml`, plus `rendering.invert_y_axis_for_screen=true`. London preserves its UTM zone 30 definition. Geometry and vehicle positions both remain in post-offset SUMO Cartesian metres.

## H. Scenario registry and selection

`GET /api/simulation/scenarios` lists stable public IDs and display metadata without loading SUMO. London entries expose J1–J5 candidate mappings and retain the multiple candidates for ambiguous J2 and J5.

`POST /api/simulation/start` accepts optional `scenario_id`: `single_intersection`, `single_intersection_emergency`, `london_normal`, `london_rush_hour`, or `london_unbalanced`. Omission preserves the synthetic default. Omitted `control_mode` selects the scenario default: `fixed` normally, `adaptive_with_emergency_priority` for `single_intersection_emergency`. Static geometry may be selected explicitly with `GET /api/simulation/network?scenario_id=london_normal`; without a query it follows the active scenario and remains synthetic while idle.

The same request accepts `control_mode` as `fixed`, `adaptive`, or `adaptive_with_emergency_priority`. Adaptive is supported for the synthetic scenario and, experimentally, for J3 only in `london_normal` and `london_unbalanced`. Emergency priority is supported only for the synthetic mapping. Unsupported combinations are rejected rather than silently reverting to fixed timing.
