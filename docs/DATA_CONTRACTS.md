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

For the synthetic scenario in adaptive mode, snapshots may additionally contain `control_reason`, a short machine-readable explanation such as `minimum_green_protected`, `hold_green_and_reevaluate`, `sustained_opposing_queue_advantage`, `opposing_approach_anti_starvation`, or `maximum_green_reached`. It is `null` before the first policy evaluation. This field describes the latest duration request, not a guarantee that a different phase has already begun. Fixed mode omits it.

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

Status also carries `control_mode`, either `fixed` or `adaptive`, for the current run. It defaults to `fixed` before a run and after stop.

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

`POST /api/simulation/start` accepts optional `scenario_id`: `single_intersection`, `london_normal`, `london_rush_hour`, or `london_unbalanced`. Omission preserves the synthetic default. Static geometry may be selected explicitly with `GET /api/simulation/network?scenario_id=london_normal`; without a query it follows the active scenario and remains synthetic while idle.

## I. Gate events (vision gate mode, `events.jsonl`)

Produced by `backend/vision` gate mode from one recorded top-down video of one intersection, for the simulation. One JSON object per line, in time order (then `track_id`). Pydantic model: `backend/models/gates.py::GateEvent`; every emitted line is validated.

```json
{"schema_version": "1.0", "event": "approach_entered", "track_id": 41, "arm": "north", "t_s": 9.801, "frame": 235, "model_id": "yolo11s_visdrone"}
{"schema_version": "1.0", "event": "intersection_entered", "track_id": 41, "arm": "north", "t_s": 12.388, "frame": 297, "model_id": "yolo11s_visdrone"}
{"schema_version": "1.0", "event": "intersection_exited", "track_id": 41, "arm": "east", "origin_arm": "north", "t_s": 17.893, "frame": 429, "model_id": "yolo11s_visdrone"}
```

- `arm` is one of `north`, `east`, `south`, `west`, named by the **side of the camera image** (`north` = top edge), not by compass bearing. Mapping arms to SUMO approaches is separate and must not be inferred from the names.
- Each arm has three hand-drawn gates (4-point pixel polygons in the scene config): `<arm>_in.far` (inbound lanes at the frame edge) emits `approach_entered`; `<arm>_in.stop` (inbound lanes just past the stop line) emits `intersection_entered`; `<arm>_out` (outbound lanes just past the crosswalk) emits `intersection_exited`.
- Gate rule: a track triggers a gate once, at the first frame where its counting point (box centre for top-down views) has been inside the gate in at least 2 of the last 3 video frames (one missed frame tolerated; configurable per scene as `gate_min_inside` of `gate_window_frames`). A frame without the track counts as not inside.
- `intersection_entered` fires **at most once per track**, on its first stop-gate trigger. A later stop-gate trigger by the same track (e.g. a left-turner whose path clips another arm's stop gate) emits no event and changes no count; the producer logs it in `gate_run.json` as suppressed (`reason: already_entered`, with track, gate, frame, and the counting point `x`/`y`).
- `origin_arm` is present only on `intersection_exited`. It is the `arm` of the same track's `intersection_entered` event, or `null` when unknown: the vehicle was already in the junction at the start, or no entry was seen for the track (e.g. the tracker lost the vehicle and it reappeared under a new ID). It is never guessed.
- `track_id` is a tracker ID, unique within one file; the same physical vehicle can appear under two IDs if the tracker loses it.
- `t_s` is seconds from the start of the video (video time, not wall-clock time); `frame` is the 0-based decoded frame index.
- Vehicles already on an approach or in the junction at the start of the video do not get the entry events they would otherwise have (see `initial` in section J); their later gate triggers do produce events.
- `model_id` is provenance (detector profile), not an instruction to consumers.

## J. Per-second gate counts (vision gate mode, `counts.jsonl`)

Produced alongside section I, for the traffic-light adaptor: one line per whole second of video, `t_s` = 0, 1, 2, ... Pydantic model: `backend/models/gates.py::GateCounts`; every emitted line is validated.

```json
{"schema_version": "1.0", "t_s": 13.0, "approaches": {"north": {"vehicles_on_approach": 6, "entered_total": 14, "discharged_total": 9}}, "in_intersection": 3, "model_id": "yolo11s_visdrone"}
```

- Values describe the state after every gate trigger with `frame / fps <= t_s`. `entered_total` counts `<arm>_in.far` triggers and `discharged_total` counts the arm's `intersection_entered` events (each track's first stop-gate trigger only) since the start (cumulative).
- `vehicles_on_approach = max(0, initial + entered_total - discharged_total)`. `initial` is the number of vehicles whose counting point lies inside the arm's approach region (convex hull of its `in.far` and `in.stop` gates) at the start, counted from tracks seen in at least 75 % of the first 0.5 s of frames, each placed where it was first seen. The `t_s = 0` line therefore uses the first 0.5 s.
- `in_intersection = max(0, initial vehicles in the junction + intersection_entered events of all arms - out-gate triggers of all arms)`. The junction is the convex hull of all stop and out gates, outside every approach region.
- Every trigger that drives a raw value below zero is a *clamp*; clamps are logged in the producer's run log (`gate_run.json`), never hidden. The clamp applies to the reported value only; later triggers move the raw value back up.
- An arm is present in `approaches` only when both of its inbound gates are configured; `in_intersection` is `null` unless all four stop and all four out gates are configured. Absent or `null` means unknown, never zero.
- **These are estimates that can drift.** They accumulate detector misses, duplicate or broken tracks, and gate-placement errors over the whole video, and there is no reset or re-synchronisation. They are camera-derived counts, not SUMO queue lengths (section B), and `vehicles_on_approach` includes moving vehicles, not only queued ones.
