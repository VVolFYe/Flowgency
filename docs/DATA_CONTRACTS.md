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

Snapshots also carry a bounded `voice_alerts` list (up to 12 recent items) for traffic events only. It is empty before the first event. Each item has `event_id` (opaque, stable within a run), `run_id`, `message_id`, `text`, `language` (`en` or `ro`), `simulation_time_s`, and `priority` (`emergency` or `routine`). The producer deduplicates state transitions, so repeated snapshots do not create new events. Current event-based snapshots emit `emergency.detected`, `emergency.priority_activated`, and `emergency.priority_completed`; activation/completion require the corresponding runner event transitions. Activation can include a request for safe clearance and does not prove the emergency approach already has green. The older requested/already-green/green-confirmed IDs are compatibility behavior only when `emergency_events` is absent. `traffic.congestion_sustained` is implemented but disabled until a calibrated scenario threshold exists. No lifecycle or UI-control action produces a voice alert. This list is presentation data and has no effect on signal decisions.

Event-based alerts also retain `emergency_event_id`, `emergency_vehicle_id`, raw `intersection_id`, and `emergency_state`. London `text` uses numbered intersection aliases derived from the sorted full controller inventory; IDs and field shapes are unchanged. Aggregate speech uses those same aliases. Consumers must continue matching events/control data by raw IDs, not parsing the text. See `docs/VOICE_ALERTS.md` for exact triggers and naming rules.

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
  "active_configuration": {
    "network": "single_intersection",
    "traffic_profile": "normal",
    "controller_mode": "fixed_timing",
    "emergency_vehicles_enabled": false
  },
  "network": "single_intersection",
  "traffic_profile": "normal",
  "controller_mode": "fixed_timing",
  "emergency_vehicles_enabled": false,
  "simulation_time_s": 42.0,
  "has_snapshot": true,
  "error": null
}
```

`state` is one of `idle`, `running`, `paused`, `finished`, or `error`. Simulation speed is simulated seconds per wall-clock second. Time is `null` before the first run; `error` is populated only when the worker fails.

`active_configuration` is `null` while idle and after Stop. Reset retains the complete active configuration but creates a new `run_id`. Controller IDs are `fixed_timing`, `adaptive_network`, and `adaptive_emergency_priority`. The emergency boolean controls only whether SUMO loads the repository-owned emergency route file; it never changes controller mode implicitly.

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

## H. Simulation configuration and selection

`GET /api/simulation/configuration-options` lists the two networks, three traffic profiles, three controller modes, and two emergency states. `GET /api/simulation/network?network=single_intersection|london` selects static geometry only; demand and controller choices never change network geometry.

`POST /api/simulation/start` accepts one validated configuration:

```json
{
  "network": "single_intersection",
  "traffic_profile": "normal",
  "controller_mode": "fixed_timing",
  "emergency_vehicles_enabled": false,
  "simulation_speed": 4.0
}
```

All 36 combinations resolve explicitly to a checked-in SUMO configuration, traffic route file, optional emergency route file, and controller adapter. Unknown IDs and non-boolean emergency values receive a validation error. Fixed and ordinary adaptive modes load emergency vehicles when enabled but do not grant preemption. `adaptive_emergency_priority` composes emergency handling with adaptive control and behaves as ordinary adaptive control when no emergency vehicle is active.

Snapshots carry `active_configuration` and `emergency_events`. Each emergency event has stable `event_id`, `emergency_vehicle_id`, `intersection_id`, approach/lane, simulation timestamps, state, and whether priority is supported. Repeated WebSocket snapshots retain the same event ID.

## I. Gate events (vision gate mode, `events.jsonl`)

Produced by `backend/vision` gate mode from one recorded top-down video of one intersection, for the simulation. One JSON object per line, in time order (then `track_id`). Pydantic model: `backend/models/gates.py::GateEvent`; every emitted line is validated.

```json
{"schema_version": "1.0", "event": "approach_entered", "track_id": 41, "arm": "north", "via": "far_gate", "t_s": 9.801, "frame": 235, "model_id": "yolo11s_visdrone"}
{"schema_version": "1.0", "event": "approach_left", "track_id": 52, "arm": "west", "via": "region", "t_s": 36.2, "frame": 868, "model_id": "yolo11s_visdrone"}
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
- **Causal.** Every event is decided from frames up to its own `frame`, never later ones, so the rules can run live; `frame` / `t_s` is the moment of the decision. All parameters below are scene fields (`backend/vision/scene.py`).
- **Warm-up.** Gate triggers before the warm-up time (`warmup_s`, default 2 s) produce no events. Vehicles on an approach or in the junction at the warm-up form the starting offset (`initial`, section J) and do not get the entry events they would otherwise have; their later gate triggers do produce events.
- **Confirmation.** A track counts towards an approach only after `min_track_frames` observations (default 10). A far-gate crossing by a younger track is applied when it is confirmed (the event carries that frame), so a short fragment that disappears first creates no arrival.
- **`approach_entered`** (additive field `via`, always written since 2026-11-15; absent in older files, where every entry was a far-gate crossing): `via: "far_gate"` when the vehicle crossed `<arm>_in.far`; `via: "region"` when it entered the arm's approach region (convex hull of its `in.far` and `in.stop` gates) without crossing the far gate, e.g. pulling out of a parking spot, or first detected or re-identified mid-approach. A region entry needs a confirmed track that has not entered the intersection and was never in the junction, inside the region in `gate_min_inside` of the last `gate_window_frames` frames. **At most one `approach_entered` per track.**
- **`approach_left`** (additive event; `via` required): the vehicle stopped being counted on `arm` without crossing its stop gate. `via: "region"`: at least `region_leave_margin_px` (15) outside the region for `region_leave_frames` (3) consecutive observations, e.g. turning into a parking spot. `via: "lost"`: not observed for `lost_s` (1.5 s, longer than the tracker keeps a lost ID; a re-identified vehicle joins again under its new ID, so it is counted twice for up to `lost_s`). `via: "obstruction"`: within `obstruction_radius_px` (25) of one point inside its region for `obstruction_s` (150 s, longer than any red light). Consumers that only read `approach_entered` (arrivals) can ignore it.
- Parked cars are excluded by position: gates and approach regions are drawn on travel lanes only. No rule uses future frames or whole-video motion.
- `model_id` is provenance (detector profile), not an instruction to consumers.

## J. Per-second gate counts (vision gate mode, `counts.jsonl`)

Produced alongside section I, for the traffic-light adaptor: one line per whole second of video, `t_s` = 0, 1, 2, ... Pydantic model: `backend/models/gates.py::GateCounts`; every emitted line is validated.

```json
{"schema_version": "1.0", "t_s": 13.0, "approaches": {"north": {"vehicles_on_approach": 6, "entered_total": 14, "discharged_total": 7, "left_total": 1}}, "in_intersection": 3, "model_id": "yolo11s_visdrone"}
```

- Values describe the state after every event with `frame / fps <= t_s` (causal, section I). Before the warm-up (`warmup_s`, default 2 s) the state is unknown: `approaches` is `{}` and `in_intersection` is `null` (the `t_s = 0` line is always present).
- `vehicles_on_approach` is the number of vehicles counted on the approach now: `initial + entered_total - discharged_total - left_total`, never negative. `initial` = confirmed tracks (at least `min_track_frames` observations) whose counting point is inside the arm's approach region at the warm-up.
- Cumulative since the warm-up: `entered_total` = the arm's `approach_entered` events (far gate and region); `discharged_total` = the arm's `intersection_entered` events by vehicles counted on this approach (an `intersection_entered` by an uncounted track, e.g. one younger than `min_track_frames`, moves no approach count; files before 2026-11-15 counted every one); `left_total` = the arm's `approach_left` events (additive field, always written since 2026-11-15, absent in older files).
- `in_intersection = max(0, initial vehicles in the junction + intersection_entered events of all arms - out-gate triggers of all arms)`. The junction is the convex hull of all stop and out gates, outside every approach region. A track that crossed a stop gate before the warm-up is in the junction at the warm-up.
- Every out trigger that drives the raw `in_intersection` below zero is a *clamp*; clamps are logged in the producer's run log (`gate_run.json`), never hidden. The clamp applies to the reported value only; later triggers move the raw value back up. `vehicles_on_approach` cannot go below zero, so it has no clamps.
- An arm is present in `approaches` only when both of its inbound gates are configured; `in_intersection` is `null` unless all four stop and all four out gates are configured. Absent or `null` means unknown, never zero.
- **These are estimates that can drift.** They accumulate detector misses, duplicate or broken tracks, and gate-placement errors over the whole video, and there is no reset or re-synchronisation. They are camera-derived counts, not SUMO queue lengths (section B), and `vehicles_on_approach` includes moving vehicles, not only queued ones.

Vision producers validate these payloads strictly with `GateEvent`, `GateCounts`, and `ApproachGateCounts`: unknown output fields are rejected so JSONL does not change silently. Offline consumers use the corresponding `GateEventInput`, `GateCountsInput`, and `ApproachGateCountsInput` models. Consumer models retain unknown optional top-level and nested fields for forward compatibility, including future emergency metadata, while known malformed fields, invalid schema versions, and incorrect `origin_arm` usage still fail validation. Optional metadata is not interpreted as vehicle demand.

`GateEventInput` accepts the same event names and `via` rules as `GateEvent`, including `approach_left` (section I). In addition, `backend.simulation.ai_input` validates that every `approach_left` follows an `approach_entered` of the same `track_id` on the same `arm`, appears at most once per track, carries no `origin_arm`, and lies inside the recording. It never creates, removes, or re-times a SUMO vehicle and is not converted into an intersection event; it is reported only as metadata (`approach_left` per arm in the timeline summary, `approach_left_events_not_demand` in the demand summary).

## K. Offline AI timeline adapter

`backend.simulation.ai_input` validates sections I/J and groups `approach_entered` events into half-open video intervals `[t_s, next_observation_t_s)`. The last interval uses the observed cadence, allowing a final partial second without fabricating another count snapshot. Each timeline point keeps event-derived arrivals separate from observed vehicle counts and cumulative totals. The summary's initial values (`initial_observed_vehicles`, `initial_in_intersection`, with `initial_observation_t_s`) come from the first counts line on which every mapped arm is known: `t_s = 0` in files produced before 2026-11-15, the warm-up line since then (earlier lines are unknown, section J). They are `null` when no such line exists. Duplicate arrival track IDs, decreasing cumulative counters, unordered input, invalid mappings, and arrivals outside the recording are rejected.

`scenarios/single_intersection/ai_arm_mapping.json` is an explicit demo convention validated against `mappings.json`. Every arm remains marked `unverified_camera_to_sumo`; it is not evidence of camera orientation or a real-world approach mapping.

## L. Offline AI-derived SUMO demand

`backend.simulation.ai_demand` creates one SUMO vehicle for each unique `approach_entered` event. Vehicle IDs are `ai_<camera_arm>_<track_id>`, departures preserve event `t_s`, and simultaneous events are ordered deterministically by video time, camera-arm order, then track ID. Unknown optional event fields do not affect vehicle type or demand.

For the synthetic MVP, each mapped incoming edge uses its single verified `dir="s"` connection. Turns are neither inferred nor generated. The camera-to-SUMO orientation remains unverified. Vehicles in the starting offset (the first counts line with every arm known: `t_s = 0` in older files, the warm-up line since 2026-11-15; `observed_at_t_s` in the summary) are recorded in summary metadata and are not inserted because their positions and arrival times are unknown. Generation fails when no counts line has every arm known, unless the caller passes the explicit opt-in `--allow-unknown-initial-observations` (also on `ai_fixed_run`, `ai_adaptive_run`, and `ai_compare --run-experiments`); the starting offset is then recorded as unknown (`observed_at_t_s`, `by_camera_arm` values and `total` are `null`, `status` is `unknown_no_complete_observation`), never as zero, and no vehicle is inserted for it.

Generated `.rou.xml` and summary JSON are runtime artifacts, not shared API payloads or tracked scenario definitions. They are not connected to a running SUMO worker in Phase 2A.

## M. Isolated fixed/adaptive AI experiments

`backend.simulation.ai_fixed_run` generates Phase 2A demand, writes an isolated runtime `.sumocfg`, and invokes stock SUMO using the unchanged `demo_01` static fixed program. `backend.simulation.ai_adaptive_run` generates the same demand and executes that configuration through adaptive TraCI control. Its default `legacy` strategy remains the existing synthetic per-step controller. The explicit experimental `gap_v1` strategy loads the audited `scenarios/single_intersection/gap_v1.experimental.json` manifest; it never falls back to legacy control. Neither strategy applies AI `intersection_entered` or `intersection_exited` timestamps to simulated vehicles, and adaptive control uses simulated SUMO traffic measurements rather than camera snapshot counts.

The reports distinguish planned AI video timestamps from actual SUMO insertion times. With the existing one-second simulation step, delays up to one step include timestep quantization; delays beyond one step indicate additional insertion-capacity pressure. Tripinfo provides completed-trip waiting time and time loss. The adaptive report also records planned-to-final-arrival duration (`SUMO arrival time - AI planned departure time`), validates observed phase order, yellow, all-red, and green bounds, and adds controller provenance: selected and runtime-verified strategy, profile, manifest path and SHA-256 where applicable, active TLS IDs, gap release count, and validation errors. Existing report fields retain their previous meanings. Collision output and per-step summary telemetry provide collision and teleport counts. Each run continues until all demand completes or its documented maximum simulation time is reached; incomplete or failed insertions remain explicit validation failures.

## N. Paired AI-demand comparison

`backend.simulation.ai_compare` compares isolated Fixed and Adaptive artifacts only after validating identical vehicle IDs, planned departures, routes, vehicle parameters, AI source hashes, network bytes, and SUMO settings. Every planned vehicle must have one completed tripinfo record and both raw diagnostics must be collision- and teleport-free. The requested adaptive strategy must match runtime provenance. Historical reports without the additive provenance object remain eligible only as legacy comparisons and cannot be relabeled as `gap_v1`.

Insertion delay (`actual SUMO depart - AI planned depart`) remains separate from SUMO waiting time. Planned-to-arrival duration (`SUMO arrival - AI planned depart`) includes insertion delay. For lower-is-better metrics, `adaptive_minus_fixed > 0` is a regression, while `absolute_improvement = fixed - adaptive > 0` is a saving. Invalid pairs do not produce comparison metrics.

## O. Analytics files, database and recorded runs

Committed JSON files, which are the source of truth for the Statistics page. The page does not fetch them directly: `python -m backend.analytics.load` copies them into a local SQLite database, and the page reads them through the read-only API in O.4. Regeneration commands are in `frontend/public/analytics/README.md`. All three formats use `schema_version: "1.0"`. `null` means unknown or not produced (for example a run that failed before writing samples), never zero. Frontend types and runtime guards are in `frontend/lib/contracts.ts`.

### O.1 Index (`index.json`)

```json
[{"id": "youtube", "label": "YouTube top-down intersection", "kind": "vision", "file": "youtube.json"}]
```

`kind` is `simulation` or `vision`. `file` is a bare file name in the same directory (`[A-Za-z0-9_.-]+.json`). `id` is the file stem. Exporters upsert their own entry (`backend/models/analytics_index.py`) after writing the file, so every entry points at an existing file.

### O.2 Simulation fixed vs adaptive (`<scenario>.json`)

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

### O.3 Vision gate counts (`youtube.json`)

Written by `python -m backend.vision.export_analytics` from section I/J files (validated with `backend/models/gates.py`):

- `kind: "vision"`.
- `source`: `{label, duration_s, duration_definition, fps, model_id, sample_readme, counts_path, events_path, video_in_repository}`. `duration_s` is the last `t_s` in `counts.jsonl`. `fps` is derived from the latest event as `frame / t_s`, or `null` without events.
- `arms`: arms present in the counts, as image sides (section I).
- `timeseries`: columnar `t_s`, `vehicles_on_approach.<arm>`, and `in_intersection` (one entry per counts line; `null` where the arm or junction is unknown).
- `flow_per_minute`: windows `(60 m, 60 (m+1)]` with `start_s`, `end_s`, `partial`, and per arm `entered` / `discharged`. Values are differences of the cumulative `entered_total` / `discharged_total`; the first window starts from zero.
- `totals.<arm>`: `{entered, discharged, peak_vehicles_on_approach}` from the last counts line and the series maximum.
- `turning_matrix`: `origins` (the arms plus `unknown`), `exits`, `counts[origin][exit]` from `intersection_exited` events (a `null` `origin_arm` is counted as `unknown`), `total_exits`, `unknown_origin_exits`.
- `limitations`: includes the first-frame offset (`vehicles_on_approach` includes initial vehicles that the totals do not count) and the top-down VisDrone model.

### O.4 Local database and read-only API

`backend/analytics/db.py` keeps two independent SQLite tables in one file. `init_db` creates both. `analytics` is written only by the loader (`python -m backend.analytics.load [--db PATH] [--index PATH]`). `runs` is written only by the simulation service (O.5), and the loader never reads or changes it:

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

The target is `$FLOWGENCY_ANALYTICS_DB` (or the loader's `--db`), default `data/analytics.sqlite3`. A relative path resolves against the repository root. A `postgresql://` or `postgres://` value selects the team's hosted Postgres instead: the same tables and constraints, plus a `seq BIGINT GENERATED ALWAYS AS IDENTITY` column that replaces SQLite's `rowid` for ordering, and `DOUBLE PRECISION` for `sim_duration_s`. The URL contains a password and is never logged or printed. For Postgres, a failed connection or a missing table returns the same 503. The file is gitignored. The `analytics` rows can be rebuilt at any time, but **deleting the file also deletes every recorded run (O.5)**, which exists nowhere else. The loader validates every index entry and file before writing anything. It upserts one row per entry, so rerunning it is idempotent. It skips listed files that are missing (with a warning) and fails on invalid JSON, an unknown kind, an unsafe file name, or a payload `kind` that differs from the index. It does not delete rows whose entry was later removed from `index.json`; delete the database file and reload to drop them.

Both routes are unauthenticated GETs, like the other read routes:

- `GET /api/analytics` returns `[{"id", "label", "kind", "schema_version", "loaded_at"}]` in first-loaded order (`index.json` order).
- `GET /api/analytics/{id}` returns the stored payload unchanged (a O.2 or O.3 document, `application/json`). An unknown id returns 404.
- If the database file is missing or has no table, both return 503 with `detail` `"Analytics database is not available; check FLOWGENCY_ANALYTICS_DB (unset = local SQLite) and run python -m backend.analytics.load"`. Reads never create the file. The first recorded run creates the file with both tables, so the list can then be empty (`[]`) instead of 503 until the loader runs.

### O.5 Recorded Live Simulation runs (`runs` table)

Every run started from the UI (`POST /api/simulation/start`) is recorded by `SimulationService` through `backend/analytics/runs.py`. The service only records when it is given a `run_sink`. `create_app()` passes `save_run` for its default service, and test services pass nothing, so tests never write the real database.

```sql
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,          -- the runner's run_id (section F snapshot run_id)
    scenario_id TEXT NOT NULL,        -- resolved scenario id (+ "_emergency"), see below
    control_mode TEXT NOT NULL,       -- controller_mode (section H): fixed_timing | adaptive_network | adaptive_emergency_priority
    status TEXT NOT NULL CHECK (status IN ('finished', 'stopped', 'error')),
    started_at TEXT NOT NULL,         -- ISO 8601 UTC with milliseconds, e.g. 2026-11-14T19:38:08.123Z
    ended_at TEXT NOT NULL,
    sim_duration_s REAL,              -- simulated seconds; NULL if unknown
    payload TEXT NOT NULL             -- the JSON document below
)
```

Recording rules:

- On start, the service remembers `run_id`, the section H configuration and `started_at`. The run's `scenario_id` is the resolved `ScenarioDefinition.scenario_id` (`single_intersection_<profile>` or `london_<profile>`), with `_emergency` appended when `emergency_vehicles_enabled` (for example `single_intersection_rush_hour_emergency`). `control_mode` is the configuration's `controller_mode`.
- Every extracted snapshot is passed to an in-memory recorder. A sample is taken at the first snapshot at or after each 5 s boundary of simulation time, counted from the start. If one step crosses several boundaries, only one sample is taken.
- Exactly one row is written when the run ends: `finished` (no pending vehicles), `stopped` (`stop`, `reset` or API shutdown), or `error` (worker or runner failure, with the message in `run.error`). A `reset` saves the previous run as `stopped` and records the restarted SUMO run as a new run. Stopping an already finished or failed run writes nothing more.
- Nothing is written inside the step loop. The write is wrapped in `try/except`, so a database failure (locked file, unwritable path, duplicate `run_id`) is logged and never changes the simulation state, status or snapshots. A run shorter than one sample is still saved, with an empty `timeseries.samples`.

Payload (`schema_version: "1.0"`, `kind: "simulation_run"`):

- `run`: `{run_id, scenario_id, legacy_scenario_id, control_mode, network, traffic_profile, controller_mode, emergency_vehicles_enabled, status, started_at, ended_at, sim_start_s, sim_end_s, sim_duration_s, sample_count, error}`. `control_mode` equals `controller_mode`; the other three are the section H configuration fields. `legacy_scenario_id` is the snapshot `scenario_id`. `sim_duration_s` = `sim_end_s − sim_start_s` from the first and last snapshot.
- `summary`: the last snapshot's `metrics` (section E, `RunMetrics.snapshot()`) copied unchanged, so its null semantics are kept: `total_time_loss_s` and `average_time_loss_s` stay `null`, and `average_waiting_time_s` is `null` with no departures. The whole `summary` is `null` if the snapshot had no `metrics`.
- `timeseries`: `interval_s` (5), `queue_measurement` (`sumo_halting_number`), and `samples`, each `{t_s, network_queue_vehicles, active_vehicle_count, departed_cumulative, arrived_cumulative, queue_by_traffic_light, queue_by_approach, phase_by_traffic_light}`. `network_queue_vehicles` is `network_queue.vehicles` (section B). The counts come from `metrics`. `queue_by_traffic_light` maps each controller to its `total_queue_vehicles`. `queue_by_approach` is the legacy `queue_lengths_by_approach` (empty for network scenarios). `phase_by_traffic_light` maps each controller to `{phase_index, phase_id}`. Missing values are `null`, never 0.
- `intersections`: one entry per traffic light, `{traffic_light_id, mean_queue_vehicles, max_queue_vehicles, sample_count}`, over the samples with a known queue. Mean and max are `null` when `sample_count` is 0.
- `phases`: one entry per traffic light, `{traffic_light_id, phase_change_count, completed_green_phases, mean_green_duration_s}`. These are observed at every simulation step, not from the 5 s samples, because 5 s sampling would miss short yellow and all-red phases. The values are held in memory, and nothing is written per step. Green uses the O.2 definition: the state contains `G`/`g` and no `y`/`Y`. The phase still running at the end is excluded. `mean_green_duration_s` is `null` with no completed green phase, or if a completed phase had an unknown state.

Read-only routes, unauthenticated like the other GETs, with the same 503 behaviour as above:

- `GET /api/analytics/runs/latest` returns the payload of the run with the latest `ended_at`, or 404 if none is recorded.
- `GET /api/analytics/runs/latest-pair?scenario_id=X` returns `{"scenario_id", "fixed", "adaptive"}`. `fixed` is the latest **finished** `fixed_timing` run of that `scenario_id` (including the `_emergency` suffix), and `adaptive` is the latest **finished** `adaptive_network` run. `adaptive_emergency_priority` runs, and stopped or failed runs, are never paired, matching the Live Simulation comparison. Either side is `null` if there is no such run. `/runs/latest` still returns the newest run of any mode and status. A missing `scenario_id` returns 422.

The Statistics page shows the latest run as its first option ("Last simulation"). It adds a fixed-vs-adaptive section when `latest-pair` has both modes for that run's scenario. These are live service runs, not the matched tripinfo comparison of O.2.

### O.6 Gemini AI review (`POST /api/analytics/insights`)

Unlike the GETs above, this route spends Gemini quota, so it requires a Bearer token with `analytics:read` (the browser calls the same-origin Next.js proxy `/api/analytics/insights`, which adds the Auth0 access token). Request body:

```json
{"entry_id": null}
```

`null` reviews the latest recorded run (`/runs/latest`) together with the latest finished `fixed_timing` and `adaptive_network` runs of its `scenario_id` (the `/runs/latest-pair` rules); a non-empty string reviews that `analytics` row (O.2 or O.3). The client never sends statistics: the backend reads the database and builds a compact prompt in `backend/insights/summary.py`. Time series become `{samples, known, min, mean, max, last}` over known values (`null` stays `null`), histograms are dropped (percentiles kept), per-controller tables become a controller count plus the top 5 by mean queue, and a pair run that is the latest run is referenced rather than repeated.

Response (`200`):

```json
{
  "source": {"kind": "latest_run", "id": "<run_id>", "scenario_id": "london_normal", "paired": true},
  "model": "gemini-3.5-flash",
  "cached": false,
  "summary": "…",
  "key_findings": ["…"],
  "suggestions": ["…"],
  "caveats": ["…"]
}
```

For an entry, `source` is `{"kind": "entry", "id": "<entry id>", "scenario_id": null, "paired": false}`. `summary` through `caveats` come from Gemini structured output (`response_schema`). `model` is `$GEMINI_MODEL` or the default in `backend/insights/gemini.py`. Results are cached in memory until the API restarts. The key is (sha256 of the trimmed summary as `json.dumps(..., sort_keys=True)`, model), computed after the data is read and summarized and before Gemini is called, so a new latest run, changed metrics for the same `run_id`, or a reloaded entry all miss the cache. `cached` reports a cache hit. Errors: 401/403 without a token or permission; 503 without `GEMINI_API_KEY`, without the `google-genai` package, or with the O.4 unavailable database (same detail); 404 when no run is recorded or the id is unknown; 422 for an unsupported stored `kind`; 502 when Gemini fails, times out (25 s, one attempt) or returns JSON that does not match the schema. The review is generated text, not a measurement.

## P. AI Traffic replay export

Replay export is explicit and optional. `--replay-output` on the isolated Fixed or Adaptive AI experiment writes one compact JSON object per authoritative SUMO step. Omitting the option preserves the existing execution and report behavior. Replay schema `1.0` records:

- `frame_index` and strictly increasing `simulation_time_s`;
- `coordinate_system` (`synthetic_cartesian_metres` for this scenario);
- vehicles sorted by ID with `x_m`, `y_m`, `angle_deg`, `speed_mps`, `lane_id`, and `edge_id` read from TraCI;
- traffic lights sorted by ID with the actual `phase_index`, `phase_id`, and red/yellow/green `state`.

Newly generated streams may also include an optional `metrics` object on every frame:

```json
{
  "cumulative_waiting_time_s": 142.0,
  "active_vehicle_count": 17,
  "arrived_vehicle_count": 39,
  "measurement": "sum_waiting_vehicle_intervals_x_step_duration"
}
```

The cumulative value is recorded after each authoritative SUMO step by counting each vehicle whose TraCI `getWaitingTime()` is positive once for that step duration. It therefore retains waiting from vehicles that later move or arrive and matches completed-trip `tripinfo waitingTime` at the end of a validated run. It must begin at zero, remain nonnegative and monotonic, and be present on every frame or none. Streams produced before this additive field remain valid; clients must display waiting history as unavailable rather than reconstructing it from speed or queue snapshots.

The stream is simulation-time data, not video frames. It continues until SUMO demand completes and is never truncated or looped at the approximately 264-second video boundary. Video event time and planned SUMO departure time share an explicit zero-second offset; actual insertion delay remains part of the experiment output.

The portable `assets/ai-traffic/versions/waiting-v1/replay_manifest.json` schema `1.0` binds the source-video identifier, H.264 Git LFS video assets, Fixed and runtime-verified `gap_v1` replay streams, single-intersection geometry API reference, independent simulation durations, comparison report, checksums, and known limitations. The asset API validates report schema, matching demand/network provenance, complete trips, zero collision/teleport diagnostics, and `gap_v1` activation at `demo_01` before returning metrics. Paths are never returned to clients. `FLOWGENCY_REPLAY_ASSET_DIR` may override this repository-relative default for custom deployments.

A second allowlisted bundle, `assets/ai-traffic/versions/demo2-v1/`, uses the same manifest schema `1.0`. For an annotated-only recording the manifest omits the `original_video` asset (it is never substituted), sets `video.duration_s` to `null`, `video.annotated_duration_s` to the browser copy's duration, `video.source_identifier` to the annotated source SHA-256, `video.source_kind` to `"annotated_only"` and `video.original_video_available` to `false`. Limitations are derived from the run reports; when the t=0 observation is unknown, the excluded-vehicle count is stated as unknown. Dataset-scoped manifests add `selection_id` (`demo1` or `demo2`). See `docs/AI_TRAFFIC_DATASETS.md`.
