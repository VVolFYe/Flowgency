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


def _finite_positive(value: float, label: str, *, allow_zero: bool = False) -> None:
    if isinstance(value, bool) or not isfinite(value) or value < 0 or (not allow_zero and value == 0):
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
