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
      "x_m": 513.2,
      "y_m": 204.8,
      "angle_deg": 178.0,
      "speed_mps": 4.2,
      "road_id": "edge_s_in"
    }
  ]
}
```

Remaining duration may be `null`. `traffic_light_id`, `current_phase_index`, and `coordinate_system` are optional additive fields introduced for simulation integration and browser rendering; existing 1.0 consumers may ignore them. `current_phase_id` is the configured human-readable SUMO phase name when available. The SUMO link-state string requires separately versioned link-index metadata; clients must not infer movements from character position alone. Vehicle snapshots may be omitted from controller-only messages.

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
  "simulation_time_s": 42.0,
  "has_snapshot": true,
  "error": null
}
```

`state` is one of `idle`, `running`, `paused`, `finished`, or `error`. Simulation speed is simulated seconds per wall-clock second. Time is `null` before the first run; `error` is populated only when the worker fails.

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
