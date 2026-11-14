"""Pure, deterministic green-budget planner for verified signal programs.

The caller supplies compatible vehicle groups and immutable transition phases.
This module cannot validate junction conflicts or pedestrian compatibility;
those belong to the scenario audit and simulation adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping


@dataclass(frozen=True)
class GreenGroup:
    group_id: str
    phase_id: str
    min_green_s: float
    max_green_s: float


@dataclass(frozen=True)
class FixedPhase:
    phase_id: str
    duration_s: float


@dataclass(frozen=True)
class CycleConfig:
    intersection_id: str
    groups: tuple[GreenGroup, ...]
    fixed_phases: tuple[FixedPhase, ...]
    green_budget_s: float
    phase_order: tuple[str, ...]
    idle_weight: float = 1.0
    max_change_s: float | None = 12.0


@dataclass(frozen=True)
class CyclePlan:
    intersection_id: str
    green_durations_s: dict[str, float]
    phase_durations_s: dict[str, float]
    phase_order: tuple[str, ...]
    measured_queues: dict[str, int]
    reason: str
    demand_scores: dict[str, float] | None = None


@dataclass(frozen=True)
class DemandObservation:
    """Normalized-input source values for one adjustable signal stage."""

    halted_vehicles: int
    approaching_vehicles: int
    mean_waiting_time_s: float
    downstream_occupancy: float


@dataclass(frozen=True)
class PressurePolicy:
    """Bounded weights for deterministic demand/pressure scoring."""

    halted_weight: float = 0.40
    approaching_weight: float = 0.25
    waiting_weight: float = 0.20
    downstream_weight: float = 0.15
    halted_scale: float = 4.0
    approaching_scale: float = 8.0
    waiting_cap_s: float = 60.0
    deadband: float = 0.08
    zero_demand_threshold: float = 0.02
    allocation_gain: float = 1.0
    low_demand_vehicle_limit: int = 3
    moderate_demand_vehicle_limit: int = 8
    high_demand_vehicle_limit: int = 16
    low_demand_max_adjustment_s: float = 1.0
    moderate_demand_max_adjustment_s: float = 3.0
    high_demand_max_adjustment_s: float = 6.0
    waiting_override_s: float = 45.0


def _finite_positive(value: float, label: str, *, allow_zero: bool = False) -> None:
    if type(value) not in (int, float) or not isfinite(value) or value < 0 or (not allow_zero and value == 0):
        raise ValueError(f"{label} must be finite and {'nonnegative' if allow_zero else 'positive'}")


def _allocate(weights: list[float], lower: list[float], upper: list[float], budget: float) -> list[float]:
    """Bounded proportional allocation with exact budget redistribution."""
    if budget < sum(lower) - 1e-9 or budget > sum(upper) + 1e-9:
        raise ValueError("green budget is infeasible under configured bounds")
    low_scale, high_scale = 0.0, max(hi / weight for hi, weight in zip(upper, weights))
    for _ in range(100):
        scale = (low_scale + high_scale) / 2
        allocated = sum(min(hi, max(lo, scale * weight)) for lo, hi, weight in zip(lower, upper, weights))
        if allocated < budget:
            low_scale = scale
        else:
            high_scale = scale
    result = [round(min(hi, max(lo, high_scale * weight)), 9) for lo, hi, weight in zip(lower, upper, weights)]
    residual = budget - sum(result)
    if abs(residual) > 1e-9:
        for i in range(len(result)):
            adjustment = min(upper[i] - result[i], residual) if residual > 0 else max(lower[i] - result[i], residual)
            result[i] += adjustment
            residual -= adjustment
            if abs(residual) <= 1e-9:
                break
    return result


def pressure_score(observation: DemandObservation, policy: PressurePolicy) -> float:
    """Return a bounded score from unlike metrics after unit normalization."""
    if type(observation.halted_vehicles) is not int or observation.halted_vehicles < 0:
        raise ValueError("halted_vehicles must be a nonnegative integer")
    if type(observation.approaching_vehicles) is not int or observation.approaching_vehicles < 0:
        raise ValueError("approaching_vehicles must be a nonnegative integer")
    for value, label in (
        (observation.mean_waiting_time_s, "mean_waiting_time_s"),
        (observation.downstream_occupancy, "downstream_occupancy"),
    ):
        _finite_positive(value, label, allow_zero=True)
    if observation.downstream_occupancy > 1:
        raise ValueError("downstream_occupancy must be between zero and one")
    for value, label in (
        (policy.halted_weight, "halted_weight"),
        (policy.approaching_weight, "approaching_weight"),
        (policy.waiting_weight, "waiting_weight"),
        (policy.downstream_weight, "downstream_weight"),
    ):
        _finite_positive(value, label, allow_zero=True)
    for value, label in (
        (policy.halted_scale, "halted_scale"),
        (policy.approaching_scale, "approaching_scale"),
        (policy.waiting_cap_s, "waiting_cap_s"),
        (policy.allocation_gain, "allocation_gain"),
    ):
        _finite_positive(value, label)
    for value, label in (
        (policy.deadband, "deadband"),
        (policy.zero_demand_threshold, "zero_demand_threshold"),
    ):
        _finite_positive(value, label, allow_zero=True)
    for value, label in (
        (policy.low_demand_max_adjustment_s, "low_demand_max_adjustment_s"),
        (policy.moderate_demand_max_adjustment_s, "moderate_demand_max_adjustment_s"),
        (policy.high_demand_max_adjustment_s, "high_demand_max_adjustment_s"),
        (policy.waiting_override_s, "waiting_override_s"),
    ):
        _finite_positive(value, label, allow_zero=True)
    demand_limits = (
        policy.low_demand_vehicle_limit,
        policy.moderate_demand_vehicle_limit,
        policy.high_demand_vehicle_limit,
    )
    if (
        any(type(value) is not int or value < 0 for value in demand_limits)
        or not demand_limits[0] < demand_limits[1] < demand_limits[2]
    ):
        raise ValueError("demand vehicle limits must be increasing nonnegative integers")
    adjustment_limits = (
        policy.low_demand_max_adjustment_s,
        policy.moderate_demand_max_adjustment_s,
        policy.high_demand_max_adjustment_s,
    )
    if not adjustment_limits[0] <= adjustment_limits[1] <= adjustment_limits[2]:
        raise ValueError("demand adjustment limits must be nondecreasing")
    if policy.waiting_override_s > policy.waiting_cap_s:
        raise ValueError("waiting_override_s cannot exceed waiting_cap_s")

    halted = observation.halted_vehicles / (
        observation.halted_vehicles + policy.halted_scale
    )
    approaching = observation.approaching_vehicles / (
        observation.approaching_vehicles + policy.approaching_scale
    )
    waiting = min(observation.mean_waiting_time_s / policy.waiting_cap_s, 1.0)
    demand = (
        policy.halted_weight * halted
        + policy.approaching_weight * approaching
        + policy.waiting_weight * waiting
        - policy.downstream_weight * observation.downstream_occupancy
    )
    return round(max(0.0, min(1.0, demand)), 9)


def plan_pressure_cycle(
    config: CycleConfig,
    observations_by_group: Mapping[str, DemandObservation],
    baseline_green_s: Mapping[str, float],
    previous_green_s: Mapping[str, float] | None = None,
    policy: PressurePolicy = PressurePolicy(),
) -> CyclePlan:
    """Allocate a stable green budget from normalized movement pressure.

    Near-equal or negligible demand recovers toward the imported baseline.
    Otherwise each baseline share is adjusted by a bounded pressure factor;
    configured green bounds and cycle-to-cycle slew limits remain authoritative.
    """
    if not config.intersection_id or len(config.groups) < 2:
        raise ValueError("intersection_id and at least two groups are required")
    _finite_positive(config.green_budget_s, "green_budget_s")
    if config.max_change_s is not None:
        _finite_positive(config.max_change_s, "max_change_s")
    ids = [group.group_id for group in config.groups]
    phase_ids = [group.phase_id for group in config.groups]
    fixed_ids = [phase.phase_id for phase in config.fixed_phases]
    if (
        any(not item for item in ids + phase_ids + fixed_ids)
        or len(set(ids)) != len(ids)
        or len(set(phase_ids + fixed_ids)) != len(phase_ids + fixed_ids)
    ):
        raise ValueError("group and phase IDs must be present and unique")
    if len(config.phase_order) != len(phase_ids + fixed_ids) or set(config.phase_order) != set(phase_ids + fixed_ids):
        raise ValueError("phase_order must list each configured phase exactly once")
    if set(observations_by_group) != set(ids) or set(baseline_green_s) != set(ids):
        raise ValueError("observations and baseline must include exactly the configured groups")
    if previous_green_s is not None and set(previous_green_s) != set(ids):
        raise ValueError("previous durations must include exactly the configured groups")

    lower: list[float] = []
    upper: list[float] = []
    baselines: list[float] = []
    scores: list[float] = []
    for group in config.groups:
        _finite_positive(group.min_green_s, "min_green_s")
        _finite_positive(group.max_green_s, "max_green_s")
        baseline = baseline_green_s[group.group_id]
        _finite_positive(baseline, "baseline_green_s")
        if group.min_green_s > baseline or baseline > group.max_green_s:
            raise ValueError("baseline green must be within configured bounds")
        lo, hi = group.min_green_s, group.max_green_s
        if previous_green_s is not None and config.max_change_s is not None:
            previous = previous_green_s[group.group_id]
            _finite_positive(previous, "previous_green_s")
            lo = max(lo, previous - config.max_change_s)
            hi = min(hi, previous + config.max_change_s)
        if lo > hi:
            raise ValueError("previous duration is incompatible with configured bounds")
        lower.append(lo)
        upper.append(hi)
        baselines.append(float(baseline))
        scores.append(pressure_score(observations_by_group[group.group_id], policy))
    for phase in config.fixed_phases:
        _finite_positive(phase.duration_s, "fixed phase duration_s")
    if abs(sum(baselines) - config.green_budget_s) > 1e-6:
        raise ValueError("baseline greens must equal the stable green budget")

    spread = max(scores) - min(scores)
    if max(scores) <= policy.zero_demand_threshold or spread <= policy.deadband:
        weights = baselines
        reason = "baseline_green_distribution_near_equal_demand"
    else:
        mean_score = sum(scores) / len(scores)
        factors = [
            min(1.5, max(0.5, 1 + policy.allocation_gain * (score - mean_score)))
            for score in scores
        ]
        pressure_weights = [
            baseline * factor for baseline, factor in zip(baselines, factors)
        ]
        pressure_allocation = _allocate(
            pressure_weights, lower, upper, config.green_budget_s
        )

        # Halted vehicles are already included in approaching vehicles. Use
        # approaching counts once for absolute demand, then blend the complete
        # budget-preserving pressure plan according to relative count/wait
        # imbalance. Sustained waiting can override a low vehicle count.
        observations = [observations_by_group[group_id] for group_id in ids]
        relevant_vehicles = sum(item.approaching_vehicles for item in observations)
        count_imbalance = (
            (max(item.approaching_vehicles for item in observations)
             - min(item.approaching_vehicles for item in observations))
            / relevant_vehicles
            if relevant_vehicles else 0.0
        )
        waiting_imbalance = min(
            1.0,
            (max(item.mean_waiting_time_s for item in observations)
             - min(item.mean_waiting_time_s for item in observations))
            / policy.waiting_cap_s,
        )
        relative_imbalance = max(count_imbalance, waiting_imbalance)

        if relevant_vehicles <= policy.low_demand_vehicle_limit:
            adjustment_limit = policy.low_demand_max_adjustment_s
        elif relevant_vehicles <= policy.moderate_demand_vehicle_limit:
            adjustment_limit = policy.moderate_demand_max_adjustment_s
        elif relevant_vehicles <= policy.high_demand_vehicle_limit:
            adjustment_limit = policy.high_demand_max_adjustment_s
        else:
            adjustment_limit = max(
                abs(value - baseline)
                for value, baseline in zip(pressure_allocation, baselines)
            )

        maximum_wait = max(item.mean_waiting_time_s for item in observations)
        maximum_raw_adjustment = max(
            abs(value - baseline)
            for value, baseline in zip(pressure_allocation, baselines)
        )
        if maximum_wait >= policy.waiting_override_s:
            waiting_range = policy.waiting_cap_s - policy.waiting_override_s
            waiting_confidence = (
                1.0 if waiting_range == 0
                else min(
                    1.0,
                    (maximum_wait - policy.waiting_override_s) / waiting_range,
                )
            )
            waiting_limit = (
                policy.high_demand_max_adjustment_s
                + waiting_confidence
                * max(
                    0.0,
                    maximum_raw_adjustment
                    - policy.high_demand_max_adjustment_s,
                )
            )
            adjustment_limit = max(adjustment_limit, waiting_limit)

        confidence = (
            min(1.0, adjustment_limit / maximum_raw_adjustment)
            * relative_imbalance
            if maximum_raw_adjustment > 0 else 0.0
        )
        weights = [
            baseline + confidence * (target - baseline)
            for baseline, target in zip(baselines, pressure_allocation)
        ]
        reason = "demand_confidence_blended_pressure_allocation"

    allocated = _allocate(weights, lower, upper, config.green_budget_s)
    greens = {group.group_id: allocated[i] for i, group in enumerate(config.groups)}
    phases = {group.phase_id: allocated[i] for i, group in enumerate(config.groups)}
    phases.update({phase.phase_id: phase.duration_s for phase in config.fixed_phases})
    return CyclePlan(
        intersection_id=config.intersection_id,
        green_durations_s=greens,
        phase_durations_s=phases,
        phase_order=config.phase_order,
        measured_queues={
            group.group_id: observations_by_group[group.group_id].halted_vehicles
            for group in config.groups
        },
        reason=reason,
        demand_scores={group.group_id: scores[i] for i, group in enumerate(config.groups)},
    )


def plan_cycle(
    config: CycleConfig,
    queues_by_group: Mapping[str, int],
    previous_green_s: Mapping[str, float] | None = None,
) -> CyclePlan:
    """Allocate one cycle's green budget from complete measured group queues.

    Call at a cycle boundary. Minimum green and fixed group order provide
    periodic service. `previous_green_s` limits cycle-to-cycle changes when
    supplied; an infeasible slew constraint is rejected instead of silently
    violating the budget or a safety bound.
    """
    if not config.intersection_id or len(config.groups) < 2:
        raise ValueError("intersection_id and at least two groups are required")
    _finite_positive(config.green_budget_s, "green_budget_s")
    _finite_positive(config.idle_weight, "idle_weight")
    if config.max_change_s is not None:
        _finite_positive(config.max_change_s, "max_change_s")
    ids = [group.group_id for group in config.groups]
    phase_ids = [group.phase_id for group in config.groups]
    fixed_ids = [phase.phase_id for phase in config.fixed_phases]
    if any(not item for item in ids + phase_ids + fixed_ids) or len(set(ids)) != len(ids) or len(set(phase_ids + fixed_ids)) != len(phase_ids + fixed_ids):
        raise ValueError("group and phase IDs must be present and unique")
    if len(config.phase_order) != len(phase_ids + fixed_ids) or set(config.phase_order) != set(phase_ids + fixed_ids):
        raise ValueError("phase_order must list each configured phase exactly once")
    if set(queues_by_group) != set(ids):
        raise ValueError("queues must include exactly the configured groups; unknown is not zero")
    if previous_green_s is not None and set(previous_green_s) != set(ids):
        raise ValueError("previous durations must include exactly the configured groups")

    lower: list[float] = []
    upper: list[float] = []
    weights: list[float] = []
    for group in config.groups:
        _finite_positive(group.min_green_s, "min_green_s")
        _finite_positive(group.max_green_s, "max_green_s")
        if group.min_green_s > group.max_green_s:
            raise ValueError("min_green_s exceeds max_green_s")
        queue = queues_by_group[group.group_id]
        if type(queue) is not int or queue < 0:
            raise ValueError("queues must be measured nonnegative integers")
        lo, hi = group.min_green_s, group.max_green_s
        if previous_green_s is not None and config.max_change_s is not None:
            previous = previous_green_s[group.group_id]
            _finite_positive(previous, "previous_green_s")
            lo = max(lo, previous - config.max_change_s)
            hi = min(hi, previous + config.max_change_s)
        if lo > hi:
            raise ValueError("previous duration is incompatible with configured bounds")
        lower.append(lo)
        upper.append(hi)
        weights.append(queue + config.idle_weight)
    for phase in config.fixed_phases:
        _finite_positive(phase.duration_s, "fixed phase duration_s")

    allocated = _allocate(weights, lower, upper, config.green_budget_s)
    greens = {group.group_id: allocated[i] for i, group in enumerate(config.groups)}
    phases = {group.phase_id: allocated[i] for i, group in enumerate(config.groups)}
    phases.update({phase.phase_id: phase.duration_s for phase in config.fixed_phases})
    return CyclePlan(
        intersection_id=config.intersection_id,
        green_durations_s=greens,
        phase_durations_s=phases,
        phase_order=config.phase_order,
        measured_queues=dict(queues_by_group),
        reason="bounded_proportional_queue_allocation_with_fixed_cycle_budget",
    )
