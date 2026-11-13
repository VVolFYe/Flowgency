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

## J3 limitation

The imported J3 program has 42/3/42/3 seconds and no explicit all-red or pedestrian phases. The planner preserves those two modeled yellow phases, but it cannot certify real-world clearance or pedestrian safety. The network audit in `scenarios/london_network/SIGNAL_SAFETY_AUDIT.md` on current `origin/main` records the link groups and remaining validation. Do not activate the planner on J3 until the simulation adapter verifies that configuration against the actual SUMO program and controlled links.

`adaptive.py` remains the earlier one-second green-extension policy for the synthetic `demo_01` scenario. It is already connected to TraCI and has different timing behavior. The cycle planner is a separate candidate for the validated London program; its results have not yet been compared with the fixed baseline in SUMO.
