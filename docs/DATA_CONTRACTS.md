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
    "southbound_in": {"car": 12, "bus": 1, "motorcycle": 2, "total": 15},
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

An adaptive London snapshot may include `adaptive_control`. `scope` identifies the versioned control profile; `active_controller_count` and `traffic_light_ids` identify controllers that passed live program validation. `fixed_controllers` maps controllers left on their imported fixed program to an explicit reason. `last_cycle_decision` remains the latest backward-compatible decision, while `last_cycle_decisions` retains the latest decision per active TLS. For gap_v1, green_durations_s reports the active green released early, and the event is emitted during that phase. Pressure-profile decisions may add normalized `demand_scores` and raw bounded demand observations. These fields never imply that an omitted or rejected controller is adaptive.

For the synthetic scenario in adaptive mode, snapshots may additionally contain `control_reason`, a short machine-readable explanation such as `minimum_green_protected`, `hold_green_and_reevaluate`, `sustained_opposing_queue_advantage`, `opposing_approach_anti_starvation`, or `maximum_green_reached`. It is `null` before the first policy evaluation. This field describes the latest duration request, not a guarantee that a different phase has already begun. Fixed mode omits it.

The synthetic emergency mode adds `hold_compatible_green_for_emergency`, `minimum_green_protected_before_emergency`, and `request_normal_clearance_for_emergency` reasons, plus `emergency_priority` with nullable `active_vehicle_id`, `active_approach`, and `reason`. Vehicle snapshots include `is_emergency`, derived from declared SUMO type IDs `ambulance`, `fire_brigade`, and `police`; it is not a YOLO inference.

Snapshots now also carry a bounded `voice_alerts` list (up to 12 recent items) for traffic events only. It is empty before the first event. Each item has `event_id` (opaque, stable within a run), `run_id`, `message_id`, `text`, `language` (`en` or `ro`), `simulation_time_s`, and `priority` (`emergency` or `routine`). The producer deduplicates state transitions, so repeated snapshots do not create new events. The current IDs are `emergency.requested`, `emergency.already_green`, and `emergency.green_confirmed`. `traffic.congestion_sustained` is implemented but disabled until a calibrated scenario threshold exists. Adaptive plan changes and the end of an emergency request do not produce voice alerts. No lifecycle or UI-control action produces a voice alert. This list is presentation data and has no effect on signal decisions.

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

`GET /api/voice/alerts/{event_id}/audio` returns `audio/mpeg` for a recent,
server-emitted alert ID. It returns 404 for an unknown or expired ID and 503 if
the backend ElevenLabs configuration or provider is unavailable. The browser
cannot submit arbitrary speech text. ElevenLabs credentials stay server-side;
captions in `voice_alerts` remain available when audio is disabled or fails.

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

The same request accepts `control_mode` as `fixed`, `adaptive`, or `adaptive_with_emergency_priority`. Adaptive is supported for the synthetic scenario and, experimentally, by the validated 22-controller network profile in `london_normal`, `london_rush_hour`, and `london_unbalanced`. The active controller count, controller IDs, and fixed fallbacks are reported in `adaptive_control`. Emergency priority is a separate mode supported only by the verified synthetic emergency scenario and is not enabled for London. Unsupported combinations are rejected rather than silently reverting to fixed timing. The historical J3-only manifest and benchmark remain separate for comparison.

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

## K. Static analytics files (`frontend/public/analytics/`)

Committed JSON files, which are the source of truth for the Statistics page. The page does not fetch them directly: `python -m backend.analytics.load` copies them into a local SQLite database, and the page reads them through the read-only API in K.4. Regeneration commands are in `frontend/public/analytics/README.md`. All three formats use `schema_version: "1.0"`. `null` means unknown or not produced (for example a run that failed before writing samples), never zero. Frontend types and runtime guards are in `frontend/lib/contracts.ts`.

### K.1 Index (`index.json`)

```json
[{"id": "youtube", "label": "YouTube top-down intersection", "kind": "vision", "file": "youtube.json"}]
```

`kind` is `simulation` or `vision`. `file` is a bare file name in the same directory (`[A-Za-z0-9_.-]+.json`). `id` is the file stem. Exporters upsert their own entry (`backend/models/analytics_index.py`) after writing the file, so every entry points at an existing file.

### K.2 Simulation fixed vs adaptive (`<scenario>.json`)

Written by `python -m backend.simulation.compare_cycles ... --analytics-out PATH`. It reuses `compare()`, `validate_run()` and `config_metadata()`, so trip metrics keep exactly the definitions of the comparison report. Top-level keys:

- `kind: "simulation"`, `scenario_id`, `scenario_name`.
- `provenance` and `experiment`: the same fields as the benchmark snapshots in `frontend/public/benchmarks/`. Paths are relative to the repository. `experiment.adaptive_scope` and `adaptive_controller_count` come from the adaptive run's reported controllers.
- `runs.<mode>`: `steps`, `cycle_decisions`.
- `summary.<metric>`: `{fixed, adaptive, absolute_improvement, percentage_improvement, better}`. A positive improvement favours adaptive. `better` is `lower`, except for throughput, which is `higher` (improvement = adaptive − fixed). `percentage_improvement` is relative to fixed and is `null` when fixed is 0. The metrics:
  - `total_waiting_time_s`, `average_waiting_time_s`, `total_time_loss_s`, `average_time_loss_s`, `average_trip_duration_s`: copied from `compare()` (tripinfo, matched completed vehicles). Averages use `compare()`'s per-vehicle saving. All are `null` when the completed vehicle sets differ.
  - `throughput_vehicles_per_hour`: completed trips × 3600 / (last arrival − config `begin`, default 0).
  - `mean_network_queue_vehicles`, `max_network_queue_vehicles`: over every simulation step.
- `timeseries`: `interval_s` (10 s, doubled until each mode has ≤ 600 samples), `queue_measurement`, and per mode a list of `{t_s, network_queue_vehicles, active_vehicles, arrived_cumulative}`. Each sample is the first step at or after an interval boundary, and the final step is always included.
- `distributions.<waiting_time_s | time_loss_s | trip_duration_s>`: `bin_edges` shared by both modes, plus per mode `{count, p50, p90, p95, max, histogram}` over completed trips. Percentiles use linear interpolation (NumPy's default method). Bins are `[edge_i, edge_i+1)`; the last bin is closed. Edges start at 0, and the width is a 1/2/2.5/5 × 10^k step aiming at 20 bins.
- `intersections`: `queue_measurement`, plus per mode a map of traffic-light ID to `{mean_queue, max_queue, mean_green_s, completed_green_phases, decision_count}`. `mean_green_s` averages completed phases whose state contains `G`/`g` and no `y`/`Y`; the phase still running at the end is excluded. `decision_count` counts the run's `cycle_decision_events` for that controller (0 in fixed mode).
- `emergency`: `null` unless a completed trip has SUMO vType `ambulance`, `fire_brigade` or `police`. Otherwise it holds `vehicle_types` plus per mode `{emergency_trip_count, normal_trip_count, emergency_average_time_loss_s, normal_average_time_loss_s}`.
- `validation`: `passed`, `matched_vehicle_count`, `errors` (prefixed with the mode), plus per mode the benchmark run shape (`passed`, `departed`, `arrived`, `completed`, `unfinished`, `duplicate_tripinfo_ids` as a count, `collisions`, `teleports`, `process_exit_code`, `terminated_by_step_limit`) and its `errors`. A failed validation is exported with `passed: false`, never dropped.
- `limitations`: strings. The exporter adds definitions plus any failed-validation, teleport and missing-sample notes; `--analytics-limitation` appends more.

Queues use `sumo_halting_number_unique_controlled_lanes`, the same measurement as `network_queue` in section B. They are SUMO state, not camera observations. The per-step samples come from `cycle_run --analytics-samples`. That opt-in file lives in the ignored run output directory; without the flag, `cycle_run` output is unchanged.

### K.3 Vision gate counts (`youtube.json`)

Written by `python -m backend.vision.export_analytics` from section I/J files (validated with `backend/models/gates.py`):

- `kind: "vision"`.
- `source`: `{label, duration_s, duration_definition, fps, model_id, sample_readme, counts_path, events_path, video_in_repository}`. `duration_s` is the last `t_s` in `counts.jsonl`. `fps` is derived from the latest event as `frame / t_s`, or `null` without events.
- `arms`: arms present in the counts, as image sides (section I).
- `timeseries`: columnar `t_s`, `vehicles_on_approach.<arm>`, and `in_intersection` (one entry per counts line; `null` where the arm or junction is unknown).
- `flow_per_minute`: windows `(60 m, 60 (m+1)]` with `start_s`, `end_s`, `partial`, and per arm `entered` / `discharged`. Values are differences of the cumulative `entered_total` / `discharged_total`; the first window starts from zero.
- `totals.<arm>`: `{entered, discharged, peak_vehicles_on_approach}` from the last counts line and the series maximum.
- `turning_matrix`: `origins` (the arms plus `unknown`), `exits`, `counts[origin][exit]` from `intersection_exited` events (a `null` `origin_arm` is counted as `unknown`), `total_exits`, `unknown_origin_exits`.
- `limitations`: includes the first-frame offset (`vehicles_on_approach` includes initial vehicles that the totals do not count) and the top-down VisDrone model.

### K.4 Local database and read-only API

`backend/analytics/db.py` keeps two independent SQLite tables in one file. `init_db` creates both. `analytics` is written only by the loader (`python -m backend.analytics.load [--db PATH] [--index PATH]`). `runs` is written only by the simulation service (K.5), and the loader never reads or changes it:

```sql
CREATE TABLE analytics (
    id TEXT PRIMARY KEY,              -- index.json id
    label TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('simulation', 'vision')),
    schema_version TEXT,              -- payload schema_version, NULL if absent
    payload TEXT NOT NULL,            -- the JSON file content, verbatim
    source_file TEXT,                 -- repository-relative path of the file
    loaded_at TEXT NOT NULL           -- ISO 8601 UTC, e.g. 2026-11-14T19:38:08Z
)
```

The path is `$FLOWGENCY_ANALYTICS_DB`, default `data/analytics.sqlite3`. A relative value resolves against the repository root. The file is gitignored. The `analytics` rows can be rebuilt at any time, but **deleting the file also deletes every recorded run (K.5)**, which exists nowhere else. The loader validates every index entry and file before writing anything. It upserts one row per entry, so rerunning it is idempotent. It skips listed files that are missing (with a warning) and fails on invalid JSON, an unknown kind, an unsafe file name, or a payload `kind` that differs from the index. It does not delete rows whose entry was later removed from `index.json`; delete the database file and reload to drop them.

Both routes are unauthenticated GETs, like the other read routes:

- `GET /api/analytics` returns `[{"id", "label", "kind", "schema_version", "loaded_at"}]` in first-loaded order (`index.json` order).
- `GET /api/analytics/{id}` returns the stored payload unchanged (a K.2 or K.3 document, `application/json`). An unknown id returns 404.
- If the database file is missing or has no table, both return 503 with `detail` `"Analytics database is not available; run python -m backend.analytics.load"`. Reads never create the file. The first recorded run creates the file with both tables, so the list can then be empty (`[]`) instead of 503 until the loader runs.

### K.5 Recorded Live Simulation runs (`runs` table)

Every run started from the UI (`POST /api/simulation/start`) is recorded by `SimulationService` through `backend/analytics/runs.py`. The service only records when it is given a `run_sink`. `create_app()` passes `save_run` for its default service, and test services pass nothing, so tests never write the real database.

```sql
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,          -- the runner's run_id (section F snapshot run_id)
    scenario_id TEXT NOT NULL,        -- scenario registry id (section H)
    control_mode TEXT NOT NULL,       -- fixed | adaptive | adaptive_with_emergency_priority
    status TEXT NOT NULL CHECK (status IN ('finished', 'stopped', 'error')),
    started_at TEXT NOT NULL,         -- ISO 8601 UTC with milliseconds, e.g. 2026-11-14T19:38:08.123Z
    ended_at TEXT NOT NULL,
    sim_duration_s REAL,              -- simulated seconds; NULL if unknown
    payload TEXT NOT NULL             -- the JSON document below
)
```

Recording rules:

- On start, the service remembers `run_id`, `scenario_id`, `control_mode` and `started_at`.
- Every extracted snapshot is passed to an in-memory recorder. A sample is taken at the first snapshot at or after each 5 s boundary of simulation time, counted from the start. If one step crosses several boundaries, only one sample is taken.
- Exactly one row is written when the run ends: `finished` (no pending vehicles), `stopped` (`stop`, `reset` or API shutdown), or `error` (worker or runner failure, with the message in `run.error`). A `reset` saves the previous run as `stopped` and records the restarted SUMO run as a new run. Stopping an already finished or failed run writes nothing more.
- Nothing is written inside the step loop. The write is wrapped in `try/except`, so a database failure (locked file, unwritable path, duplicate `run_id`) is logged and never changes the simulation state, status or snapshots. A run shorter than one sample is still saved, with an empty `timeseries.samples`.

Payload (`schema_version: "1.0"`, `kind: "simulation_run"`):

- `run`: `{run_id, scenario_id, legacy_scenario_id, control_mode, status, started_at, ended_at, sim_start_s, sim_end_s, sim_duration_s, sample_count, error}`. `legacy_scenario_id` is the snapshot `scenario_id`. `sim_duration_s` = `sim_end_s − sim_start_s` from the first and last snapshot.
- `summary`: the last snapshot's `metrics` (section E, `RunMetrics.snapshot()`) copied unchanged, so its null semantics are kept: `total_time_loss_s` and `average_time_loss_s` stay `null`, and `average_waiting_time_s` is `null` with no departures. The whole `summary` is `null` if the snapshot had no `metrics`.
- `timeseries`: `interval_s` (5), `queue_measurement` (`sumo_halting_number`), and `samples`, each `{t_s, network_queue_vehicles, active_vehicle_count, departed_cumulative, arrived_cumulative, queue_by_traffic_light, queue_by_approach, phase_by_traffic_light}`. `network_queue_vehicles` is `network_queue.vehicles` (section B). The counts come from `metrics`. `queue_by_traffic_light` maps each controller to its `total_queue_vehicles`. `queue_by_approach` is the legacy `queue_lengths_by_approach` (empty for network scenarios). `phase_by_traffic_light` maps each controller to `{phase_index, phase_id}`. Missing values are `null`, never 0.
- `intersections`: one entry per traffic light, `{traffic_light_id, mean_queue_vehicles, max_queue_vehicles, sample_count}`, over the samples with a known queue. Mean and max are `null` when `sample_count` is 0.
- `phases`: one entry per traffic light, `{traffic_light_id, phase_change_count, completed_green_phases, mean_green_duration_s}`. These are observed at every simulation step, not from the 5 s samples, because 5 s sampling would miss short yellow and all-red phases. The values are held in memory, and nothing is written per step. Green uses the K.2 definition: the state contains `G`/`g` and no `y`/`Y`. The phase still running at the end is excluded. `mean_green_duration_s` is `null` with no completed green phase, or if a completed phase had an unknown state.

Read-only routes, unauthenticated like the other GETs, with the same 503 behaviour as above:

- `GET /api/analytics/runs/latest` returns the payload of the run with the latest `ended_at`, or 404 if none is recorded.
- `GET /api/analytics/runs/latest-pair?scenario_id=X` returns `{"scenario_id", "fixed", "adaptive"}`. `fixed` is the latest `fixed` run of that scenario, and `adaptive` is the latest `adaptive` or `adaptive_with_emergency_priority` run. Either is `null` if not recorded. Any status counts, and the page warns when a run did not finish. A missing `scenario_id` returns 422.

The Statistics page shows the latest run as its first option ("Last simulation"). It adds a fixed-vs-adaptive section when `latest-pair` has both modes for that run's scenario. These are live service runs, not the matched tripinfo comparison of K.2.
