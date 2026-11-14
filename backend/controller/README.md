# Adaptive cycle planner

`cycle_planner.py` is a pure Python planner. It does not import SUMO or TraCI and does not modify a signal. The simulation owner must first verify compatible vehicle groups, link indices, phase order, pedestrian movements, and clearance intervals. The planner only allocates the configured green budget; every fixed transition phase retains its duration.

## Interface

```python
from backend.controller.cycle_planner import CycleConfig, FixedPhase, GreenGroup, plan_cycle

j3 = CycleConfig(
    intersection_id="J3",
    groups=(
        GreenGroup("brixton", "j3_phase_0", 20, 64),
        GreenGroup("vassall_caldwell", "j3_phase_2", 20, 64),
    ),
    fixed_phases=(
        FixedPhase("j3_phase_1_yellow", 3),
        FixedPhase("j3_phase_3_yellow", 3),
    ),
    green_budget_s=84,
    phase_order=("j3_phase_0", "j3_phase_1_yellow", "j3_phase_2", "j3_phase_3_yellow"),
)

plan = plan_cycle(
    j3,
    {"brixton": 100, "vassall_caldwell": 0},
    previous_green_s={"brixton": 42, "vassall_caldwell": 42},
)
```

Result: `plan.green_durations_s == {"brixton": 54, "vassall_caldwell": 30}`. The first cycle without `previous_green_s` would be `{64, 20}`. `plan.phase_durations_s` also contains both unchanged 3-second yellow phases, `plan.phase_order` repeats the configured order, and `plan.measured_queues` and `plan.reason` support logging. The `j3_phase_*` strings above are **planner labels**, not verified SUMO phase names; the adapter must map them to J3's audited phase indices 0–3.

For each group, weight is `measured_queue + idle_weight` (default `1`). The plan allocates `green_budget_s` proportionally, clamps each green to its configured minimum/maximum, and redistributes any excess to other groups while preserving the budget. This generalizes the proposed two-group formula. When a previous plan is supplied, each green is additionally bounded to `previous ± max_change_s` (default `12`). A measured zero is valid; a missing group, negative count, invalid duration, or infeasible budget raises `ValueError`. There is no automatic conversion of unknown to zero.

The minimum green and a fixed recurring phase order provide periodic service to every configured group. `max_change_s` prevents a large cycle-to-cycle jump, but it can be disabled by setting `None`. Waiting-time weighting and across-intersection coordination are not implemented; queue counts alone do not prove globally optimal traffic flow. Plans should be computed at a cycle boundary from a documented observation window, then held for that cycle. If the previous-plan constraints are infeasible, the caller must retain a validated safe plan and report the error.

## London safety limitations

The imported J3 program has 42/3/42/3 seconds and no explicit all-red or pedestrian phases. The planner preserves those two modeled yellow phases, but it cannot certify real-world clearance or pedestrian safety. The network audit in `docs/audits/adaptive_network_audit.md` records the wider program review and remaining validation. The simulation service enables experimental London control only after its adapter verifies the selected program, adjustable green phases, controlled links, and expected TLS set against the live SUMO network.

`adaptive.py` remains the earlier one-second green-extension policy for the synthetic `demo_01` scenario and has different timing behavior. When it requests the end of a green, it marks that phase as transition-pending and sends the short remaining-duration command only once; repeated commands would continually postpone SUMO's switch time. The marker clears when SUMO reports the next phase, leaving yellow and all-red timing to the installed program. London Normal, Rush Hour, and Unbalanced can use the experimental network pressure profile; controllers that fail structural validation remain fixed with an explicit reason. The historical J3-only manifest and benchmark are retained unchanged.

`emergency.py` is a pure preference layer for the same verified synthetic signal. The runner recognizes only declared SUMO emergency type IDs on mapped incoming edges or while crossing the junction. An opposing request may end the current green only after its normal 10-second minimum; SUMO then executes its 3-second yellow and 2-second all-red. A compatible request keeps the current green in short increments, including beyond the normal 45-second maximum, until the selected vehicle leaves the junction. The existing active request remains selected when simultaneous requests arrive; otherwise the oldest observed vehicle ID wins. The controller never writes a signal-state string. The synthetic network has no pedestrian phases, and this experiment is not enabled for London.

The ordinary synthetic policy sends its one-second phase-ending request only once. Emergency priority uses zero remaining duration after the conflicting green minimum to enter the installed yellow phase on the next simulation step. Neither path skips the all-red phase.

## Generic SUMO adapter

`backend/simulation/cycle_adapter.py` supports both the historical explicit J3 manifest and the network discovery profile. The explicit profile validates every configured phase and link against TraCI. The network profile derives principal adjustable green stages from the live program, excludes link indices shared by multiple stages, and leaves short continuation, yellow, mixed-transition, and clearance phases unchanged. It measures movement demand using each vehicle's next TLS link index, so shared incoming lanes are not counted twice across stages. At cycle boundaries it computes one independent plan per eligible controller and changes only green dwell durations as those phases begin. It never writes a red/yellow/green state string or skips a phase. Invalid or structurally unsupported controllers fall back to fixed timing and are reported explicitly.

The network pressure plan is confidence-blended toward each imported baseline. Approaching vehicles provide the absolute demand count; halted vehicles are not added again because they are already part of that count. With the current experimental policy, 0–3 relevant vehicles permit at most ±1 second from baseline, 4–8 permit ±3 seconds, 9–16 permit ±6 seconds, and stronger demand may use the existing audited bounds. Relative count or waiting imbalance scales the adjustment. Mean waiting of 45 seconds begins an anti-starvation override, reaching the existing bound at the configured 60-second waiting cap. These are deterministic MVP constraints, not universal real-world timing recommendations.

The first cycle is bounded against the configured fixed durations; later cycles are bounded against the previous plan. A simulation can contain multiple independent controllers in the manifest. Camera observations belong upstream: they may generate or calibrate SUMO demand, while this controller reacts to **simulated** queues. Missing camera coverage must not be converted to a zero queue or silently mapped to a SUMO lane.

Run the synthetic junction with the reusable planner:

```bash
python3 -m backend.simulation.cycle_run --config scenarios/single_intersection/demo.sumocfg --adaptive-manifest scenarios/single_intersection/adaptive.json
```

For the J3 simulation experiment after checking its phase/link mapping in SUMO-GUI:

```bash
python3 -m backend.simulation.cycle_run --config scenarios/london_network/configs/unbalanced.sumocfg --adaptive-manifest scenarios/london_network/j3_adaptive.experimental.json
```

Omit `--adaptive-manifest` to run the same SUMO configuration with fixed timings. The J3 manifest is explicitly experimental: the imported model has no all-red or pedestrian stages, and real-world signal safety has not been validated. A new intersection requires a new reviewed manifest; one cannot infer safe phases from camera coordinates or road names. The same adapter and planner code are reused without modification.

Add `--trace-phases` to print each observed SUMO phase entry and verify actual interval lengths. TraCI's `setPhaseDuration` accepts **remaining** time, so the adapter subtracts time already spent in the green phase from the planned total before sending the command. This matters when a phase transition is first observed after a simulation step.

To watch the adaptive run in SUMO-GUI, use `--sumo-binary sumo-gui --step-delay-ms 150`. This adds 150 ms of real time between simulated one-second steps; it does not change simulation timing or phase decisions. A WSL environment needs working Linux GUI support (such as WSLg). The first observed phase boundary may be at 71 s due to SUMO's initial step; subsequent complete cycles should match the configured 70 s.

To measure whether adaptive timing helped on identical vehicles and demand, run:

```bash
python3 -m backend.simulation.compare_cycles --config scenarios/single_intersection/peak.sumocfg --adaptive-manifest scenarios/single_intersection/adaptive.json
```

The report pairs completed vehicle IDs and prints fixed/adaptive averages plus seconds saved for waiting time, time loss, and trip duration. Positive savings favor adaptive; negative savings favor fixed. It also reports arrivals, collisions, and teleports. The two runs write separate ignored outputs under the scenario's `output/` directory. Repeat on `demo.sumocfg` and, after J3 validation, London `normal` and `unbalanced`; one profile is not proof of general improvement.
