"""Verified TraCI adapters for fixed-budget adaptive signal programs."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from backend.controller.cycle_planner import (
    CycleConfig,
    DemandObservation,
    FixedPhase,
    GreenGroup,
    PressurePolicy,
    plan_cycle,
    plan_pressure_cycle,
)


@dataclass(frozen=True)
class AdaptiveLoadResult:
    profile_id: str
    signals: tuple["AdaptiveSignal", ...]
    fixed_controllers: dict[str, str]


def collect_vehicle_observations(
    connection: Any,
    traffic_light_ids: Iterable[str],
    *,
    approach_distance_m: float,
) -> dict[str, list[dict[str, float | int | str]]]:
    """Classify approaching vehicles once per step by their next TLS link."""
    targets = set(traffic_light_ids)
    observations: dict[str, list[dict[str, float | int | str]]] = {
        traffic_light_id: [] for traffic_light_id in targets
    }
    if not targets:
        return observations
    vehicle = connection.vehicle
    for vehicle_id in vehicle.getIDList():
        for tls_id, link_index, distance_m, _state in vehicle.getNextTLS(vehicle_id):
            if tls_id not in targets or not 0 <= float(distance_m) <= approach_distance_m:
                continue
            observations[tls_id].append(
                {
                    "vehicle_id": vehicle_id,
                    "link_index": int(link_index),
                    "distance_m": float(distance_m),
                    "speed_mps": float(vehicle.getSpeed(vehicle_id)),
                    "waiting_time_s": max(0.0, float(vehicle.getWaitingTime(vehicle_id))),
                }
            )
    return observations


class AdaptiveSignal:
    """Own one TLS; change only audited green dwell at phase entry."""

    def __init__(self, specification: dict[str, Any], connection: Any) -> None:
        self.spec = specification
        self.connection = connection
        self.tls_id = specification["traffic_light_id"]
        self.phases = specification["phases"]
        self.groups = specification["groups"]
        self.strategy = specification.get("strategy", "queue_proportional_v1")
        self._phase_seen: int | None = None
        self._plan = None
        self._lanes: dict[str, tuple[str, ...]] = {}
        self._downstream_lanes: dict[str, tuple[str, ...]] = {}
        self._group_links: dict[str, frozenset[int]] = {}
        self._sample_totals: dict[str, dict[str, float]] = {}
        self._sample_count = 0
        self._smoothed_observations: dict[str, DemandObservation] | None = None
        self._validate_program()
        self._validate_corridor_guards()
        self._reset_measurement_window()

    @property
    def approach_distance_m(self) -> float:
        return float(self.spec.get("measurement", {}).get("approach_distance_m", 150.0))

    def _validate_program(self) -> None:
        light = self.connection.trafficlight
        if self.tls_id not in light.getIDList():
            raise ValueError(f"unknown traffic light {self.tls_id}")
        if light.getProgram(self.tls_id) != self.spec["program_id"]:
            raise ValueError(f"unexpected program for {self.tls_id}")
        logics = [
            logic for logic in light.getAllProgramLogics(self.tls_id)
            if logic.programID == self.spec["program_id"]
        ]
        if len(logics) != 1 or len(logics[0].phases) != len(self.phases):
            raise ValueError(f"phase count/program mismatch for {self.tls_id}")
        if [phase["index"] for phase in self.phases] != list(range(len(self.phases))):
            raise ValueError("phases must list every SUMO index in order")
        for expected, actual in zip(self.phases, logics[0].phases):
            if expected["state"] != actual.state or abs(expected["duration_s"] - actual.duration) > 1e-6:
                raise ValueError(f"phase {expected['index']} differs from audited program")

        links = light.getControlledLinks(self.tls_id)
        seen_indices: set[int] = set()
        group_ids = {group["group_id"] for group in self.groups}
        if len(group_ids) != len(self.groups) or len(self.groups) < 2:
            raise ValueError("at least two unique green groups are required")
        if {phase.get("group_id") for phase in self.phases if "group_id" in phase} != group_ids:
            raise ValueError("each group must own one green phase")
        if len([phase for phase in self.phases if "group_id" in phase]) != len(self.groups):
            raise ValueError("each group must own exactly one green phase")

        for group in self.groups:
            indices = group["link_indices"]
            if not indices or any(type(i) is not int or i < 0 or i >= len(links) for i in indices):
                raise ValueError("group has invalid controlled link indices")
            if seen_indices.intersection(indices):
                raise ValueError("controlled link assigned to multiple groups")
            seen_indices.update(indices)
            incoming = {link[0] for i in indices for link in links[i]}
            downstream = {link[1] for i in indices for link in links[i]}
            if not incoming or not downstream:
                raise ValueError("group has no controlled incoming/downstream lanes")
            group_id = group["group_id"]
            self._lanes[group_id] = tuple(sorted(incoming))
            self._downstream_lanes[group_id] = tuple(sorted(downstream))
            self._group_links[group_id] = frozenset(indices)
            own = next(phase for phase in self.phases if phase.get("group_id") == group_id)
            if group["phase_index"] != own["index"]:
                raise ValueError("group phase index differs from audited phase")
            for index in indices:
                if own["state"][index] not in "Gg":
                    raise ValueError("group link is not green in its configured phase")
                if any(
                    phase["state"][index] not in "rR"
                    for phase in self.phases
                    if phase.get("group_id") not in (None, group_id)
                ):
                    raise ValueError("exclusive group link is active in another adjustable green")

        shared_lanes = any(
            set(first).intersection(second)
            for position, first in enumerate(self._lanes.values())
            for second in list(self._lanes.values())[position + 1 :]
        )
        if shared_lanes and self.strategy != "pressure_v1":
            raise ValueError("incoming lane belongs to multiple groups")
        if self.strategy not in {"queue_proportional_v1", "pressure_v1"}:
            raise ValueError(f"unknown adaptive strategy {self.strategy}")

    def _validate_corridor_guards(self) -> None:
        light = self.connection.trafficlight
        upstream_links = light.getControlledLinks(self.tls_id)
        for guard in self.spec.get("corridor_guards", []):
            phase_index = guard.get("upstream_phase_index")
            group = next(
                (item for item in self.groups if item["phase_index"] == phase_index),
                None,
            )
            if group is None:
                raise ValueError("corridor guard phase is not an adjustable green")
            minimum_space = guard.get("minimum_receiving_space_m")
            if type(minimum_space) not in (int, float) or minimum_space <= 0:
                raise ValueError("corridor guard minimum receiving space must be positive")
            movements = guard.get("movements")
            if not isinstance(movements, list) or not movements:
                raise ValueError("corridor guard requires verified movements")
            for movement in movements:
                upstream_index = movement.get("upstream_link_index")
                downstream_id = movement.get("downstream_traffic_light_id")
                downstream_index = movement.get("downstream_link_index")
                lane_id = movement.get("receiving_lane_id")
                if (
                    type(upstream_index) is not int
                    or upstream_index not in group["link_indices"]
                    or type(downstream_index) is not int
                    or downstream_id not in light.getIDList()
                ):
                    raise ValueError("corridor guard has an unverified controller link")
                downstream_links = light.getControlledLinks(downstream_id)
                if not 0 <= downstream_index < len(downstream_links):
                    raise ValueError("corridor guard downstream link index is invalid")
                upstream_targets = {
                    link[1] for link in upstream_links[upstream_index]
                }
                downstream_sources = {
                    link[0] for link in downstream_links[downstream_index]
                }
                if lane_id not in upstream_targets or lane_id not in downstream_sources:
                    raise ValueError("corridor guard lane does not connect the configured links")

    def _signal_is_green_during(
        self,
        traffic_light_id: str,
        link_index: int,
        start_s: float,
        end_s: float,
    ) -> bool:
        """Conservatively forecast one downstream link from its live next switch."""
        light = self.connection.trafficlight
        now = float(self.connection.simulation.getTime())
        if start_s < now or end_s < start_s:
            return False
        program_id = light.getProgram(traffic_light_id)
        logics = [
            logic for logic in light.getAllProgramLogics(traffic_light_id)
            if logic.programID == program_id
        ]
        if len(logics) != 1:
            return False
        phases = logics[0].phases
        phase_index = int(light.getPhase(traffic_light_id))
        segment_start = now
        segment_end = float(light.getNextSwitch(traffic_light_id))
        # The current switch is authoritative. Future phases use the audited
        # imported durations; any unavailable or ambiguous forecast is blocked.
        for _ in range(len(phases) * 3):
            if segment_end > start_s and segment_start < end_s:
                state = str(phases[phase_index].state)
                if link_index >= len(state) or state[link_index] not in "Gg":
                    return False
            if segment_end >= end_s:
                return True
            phase_index = (phase_index + 1) % len(phases)
            segment_start = segment_end
            segment_end += float(phases[phase_index].duration)
        return False

    def _apply_corridor_guards(
        self, plan: Any, baseline: dict[str, float]
    ) -> tuple[Any, list[dict[str, Any]]]:
        outcomes: list[dict[str, Any]] = []
        if not self.spec.get("corridor_guards"):
            return plan, outcomes
        now = float(self.connection.simulation.getTime())
        for guard in self.spec.get("corridor_guards", []):
            phase_index = int(guard["upstream_phase_index"])
            group_id = self.phases[phase_index]["group_id"]
            target = float(plan.green_durations_s[group_id])
            imported = baseline[group_id]
            if target <= imported + 1e-9:
                continue
            phase_start_offset = sum(
                float(plan.phase_durations_s[f"phase_{index}"])
                for index in range(phase_index)
            )
            constrained_reasons: list[str] = []
            for movement in guard["movements"]:
                lane_id = movement["receiving_lane_id"]
                lane_length = float(self.connection.lane.getLength(lane_id))
                max_speed = float(self.connection.lane.getMaxSpeed(lane_id))
                occupancy = max(0.0, min(
                    100.0,
                    float(self.connection.lane.getLastStepOccupancy(lane_id)),
                ))
                available_space = lane_length * (1.0 - occupancy / 100.0)
                if available_space < float(guard["minimum_receiving_space_m"]):
                    constrained_reasons.append(f"{lane_id}:insufficient_storage")
                    continue
                travel_time = lane_length / max_speed if max_speed > 0 else float("inf")
                arrival_start = now + phase_start_offset + imported + travel_time
                arrival_end = now + phase_start_offset + target + travel_time
                if not self._signal_is_green_during(
                    movement["downstream_traffic_light_id"],
                    int(movement["downstream_link_index"]),
                    arrival_start,
                    arrival_end,
                ):
                    constrained_reasons.append(f"{lane_id}:downstream_not_green")
            if constrained_reasons:
                phase_durations = dict(plan.phase_durations_s)
                phase_durations.update({
                    f"phase_{group['phase_index']}": baseline[group["group_id"]]
                    for group in self.groups
                })
                plan = replace(
                    plan,
                    green_durations_s=dict(baseline),
                    phase_durations_s=phase_durations,
                    reason=f"{plan.reason};corridor_guard_baseline",
                )
                outcomes.append({
                    "guard_id": guard["guard_id"],
                    "action": "baseline_green_distribution",
                    "reasons": constrained_reasons,
                })
        return plan, outcomes

    def _cycle_config(self) -> CycleConfig:
        return CycleConfig(
            intersection_id=self.spec["intersection_id"],
            groups=tuple(
                GreenGroup(
                    group["group_id"], f"phase_{group['phase_index']}",
                    group["min_green_s"], group["max_green_s"],
                )
                for group in self.groups
            ),
            fixed_phases=tuple(
                FixedPhase(f"phase_{phase['index']}", phase["duration_s"])
                for phase in self.phases if "group_id" not in phase
            ),
            green_budget_s=self.spec["green_budget_s"],
            phase_order=tuple(f"phase_{phase['index']}" for phase in self.phases),
            max_change_s=self.spec.get("max_change_s", 12.0),
        )

    def _baseline(self) -> dict[str, float]:
        return {
            group["group_id"]: float(self.phases[group["phase_index"]]["duration_s"])
            for group in self.groups
        }

    def _reset_measurement_window(self) -> None:
        self._sample_totals = {
            group["group_id"]: {
                "halted": 0.0, "approaching": 0.0,
                "waiting": 0.0, "downstream": 0.0,
            }
            for group in self.groups
        }
        self._sample_count = 0

    def _record_pressure_sample(
        self, vehicle_observations: list[dict[str, float | int | str]]
    ) -> None:
        halting_speed = float(
            self.spec.get("measurement", {}).get("halting_speed_mps", 0.1)
        )
        for group in self.groups:
            group_id = group["group_id"]
            records = [
                record for record in vehicle_observations
                if int(record["link_index"]) in self._group_links[group_id]
                and float(record["distance_m"]) <= self.approach_distance_m
            ]
            halted = sum(float(record["speed_mps"]) < halting_speed for record in records)
            waiting = (
                sum(float(record["waiting_time_s"]) for record in records) / len(records)
                if records else 0.0
            )
            occupancies = [
                max(0.0, min(1.0, float(
                    self.connection.lane.getLastStepOccupancy(lane_id)
                ) / 100.0))
                for lane_id in self._downstream_lanes[group_id]
            ]
            totals = self._sample_totals[group_id]
            totals["halted"] += halted
            totals["approaching"] += len(records)
            totals["waiting"] += waiting
            totals["downstream"] += sum(occupancies) / len(occupancies)
        self._sample_count += 1

    def _window_observations(self) -> dict[str, DemandObservation]:
        if self._sample_count == 0:
            current = {
                group["group_id"]: DemandObservation(0, 0, 0.0, 0.0)
                for group in self.groups
            }
        else:
            current = {
                group_id: DemandObservation(
                    int(round(values["halted"] / self._sample_count)),
                    int(round(values["approaching"] / self._sample_count)),
                    values["waiting"] / self._sample_count,
                    values["downstream"] / self._sample_count,
                )
                for group_id, values in self._sample_totals.items()
            }
        alpha = float(self.spec.get("measurement", {}).get("smoothing", 0.5))
        if not 0 < alpha <= 1:
            raise ValueError("measurement smoothing must be in (0, 1]")
        if self._smoothed_observations is None:
            smoothed = current
        else:
            smoothed = {
                group_id: DemandObservation(
                    int(round(alpha * observation.halted_vehicles + (1 - alpha) * self._smoothed_observations[group_id].halted_vehicles)),
                    int(round(alpha * observation.approaching_vehicles + (1 - alpha) * self._smoothed_observations[group_id].approaching_vehicles)),
                    alpha * observation.mean_waiting_time_s + (1 - alpha) * self._smoothed_observations[group_id].mean_waiting_time_s,
                    alpha * observation.downstream_occupancy + (1 - alpha) * self._smoothed_observations[group_id].downstream_occupancy,
                )
                for group_id, observation in current.items()
            }
        self._smoothed_observations = smoothed
        return smoothed

    def _make_plan(self) -> tuple[Any, dict[str, Any]]:
        config = self._cycle_config()
        baseline = self._baseline()
        previous = baseline if self._plan is None else self._plan.green_durations_s
        if self.strategy == "pressure_v1":
            observations = self._window_observations()
            plan = plan_pressure_cycle(
                config, observations, baseline, previous,
                PressurePolicy(**self.spec.get("pressure_policy", {})),
            )
            details = {
                group_id: {
                    "halted_vehicles": observation.halted_vehicles,
                    "approaching_vehicles": observation.approaching_vehicles,
                    "mean_waiting_time_s": round(observation.mean_waiting_time_s, 3),
                    "downstream_occupancy": round(observation.downstream_occupancy, 6),
                }
                for group_id, observation in observations.items()
            }
            plan, guard_outcomes = self._apply_corridor_guards(plan, baseline)
            if guard_outcomes:
                details["corridor_guards"] = guard_outcomes
            self._reset_measurement_window()
            return plan, details
        queues = {
            group_id: sum(int(self.connection.lane.getLastStepHaltingNumber(lane_id)) for lane_id in lanes)
            for group_id, lanes in self._lanes.items()
        }
        return plan_cycle(config, queues, previous), {}

    def tick(
        self,
        vehicle_observations: list[dict[str, float | int | str]] | None = None,
    ) -> dict[str, Any] | None:
        """Observe one step and apply a plan only at verified phase entries."""
        light = self.connection.trafficlight
        phase_index = int(light.getPhase(self.tls_id))
        if self._phase_seen is None and phase_index != 0:
            if self.strategy == "pressure_v1":
                self._record_pressure_sample(vehicle_observations or [])
            return None
        if phase_index == self._phase_seen:
            if self.strategy == "pressure_v1":
                self._record_pressure_sample(vehicle_observations or [])
            return None
        if phase_index != (0 if self._phase_seen is None else (self._phase_seen + 1) % len(self.phases)):
            raise RuntimeError(f"unexpected phase transition for {self.tls_id}")
        if light.getRedYellowGreenState(self.tls_id) != self.phases[phase_index]["state"]:
            raise RuntimeError(f"unexpected signal state for {self.tls_id}")

        completing_cycle = phase_index == 0 and self._phase_seen is not None
        self._phase_seen = phase_index
        phase = self.phases[phase_index]
        details: dict[str, Any] = {}
        if phase_index == 0:
            if self.strategy == "pressure_v1" and not completing_cycle:
                self._reset_measurement_window()
            self._plan, details = self._make_plan()
        if "group_id" in phase and self._plan is not None:
            target = self._plan.green_durations_s[phase["group_id"]]
            if hasattr(light, "getSpentDuration"):
                spent = float(light.getSpentDuration(self.tls_id))
            else:
                spent = float(light.getPhaseDuration(self.tls_id)) - (
                    float(light.getNextSwitch(self.tls_id))
                    - float(self.connection.simulation.getTime())
                )
            remaining = target - spent
            if remaining <= 0:
                raise RuntimeError(f"green phase already exceeded its planned duration at {self.tls_id}")
            light.setPhaseDuration(self.tls_id, remaining)
        if self.strategy == "pressure_v1":
            self._record_pressure_sample(vehicle_observations or [])
        if phase_index == 0 and self._plan is not None:
            return {
                "intersection_id": self.spec["intersection_id"],
                "traffic_light_id": self.tls_id,
                "strategy": self.strategy,
                "queues": self._plan.measured_queues,
                "demand_scores": self._plan.demand_scores,
                "demand_observations": details,
                "green_durations_s": self._plan.green_durations_s,
                "reason": self._plan.reason,
            }
        return None


def _derive_controller_spec(
    traffic_light_id: str,
    discovery: dict[str, Any],
    connection: Any,
    corridor_guards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    light = connection.trafficlight
    program_id = light.getProgram(traffic_light_id)
    logics = [logic for logic in light.getAllProgramLogics(traffic_light_id) if logic.programID == program_id]
    if len(logics) != 1:
        raise ValueError("active program does not have exactly one matching logic")
    minimum_duration = float(discovery.get("minimum_adjustable_green_s", 20.0))
    adjustment = float(discovery.get("maximum_green_adjustment_s", 12.0))
    minimum_green = float(discovery.get("minimum_green_s", 10.0))
    phases: list[dict[str, Any]] = []
    candidate_links: dict[int, set[int]] = {}
    for index, phase in enumerate(logics[0].phases):
        state, duration = str(phase.state), float(phase.duration)
        phases.append({"index": index, "state": state, "duration_s": duration})
        active = {position for position, signal in enumerate(state) if signal in "Gg"}
        if duration >= minimum_duration and active and not any(signal in "yY" for signal in state):
            candidate_links[index] = active
    if len(candidate_links) < 2:
        raise ValueError("fewer than two adjustable principal green stages")
    frequency = {
        link_index: sum(link_index in links for links in candidate_links.values())
        for links in candidate_links.values() for link_index in links
    }
    groups: list[dict[str, Any]] = []
    for phase_index, active in candidate_links.items():
        exclusive = sorted(index for index in active if frequency[index] == 1)
        if not exclusive:
            raise ValueError(f"principal phase {phase_index} has no exclusive controlled links")
        baseline = phases[phase_index]["duration_s"]
        group_id = f"phase_{phase_index}"
        phases[phase_index]["group_id"] = group_id
        groups.append({
            "group_id": group_id,
            "phase_index": phase_index,
            "link_indices": exclusive,
            "min_green_s": max(minimum_green, baseline - adjustment),
            "max_green_s": baseline + adjustment,
        })
    return {
        "intersection_id": traffic_light_id,
        "traffic_light_id": traffic_light_id,
        "program_id": program_id,
        "strategy": "pressure_v1",
        "green_budget_s": sum(phases[group["phase_index"]]["duration_s"] for group in groups),
        "max_change_s": float(discovery.get("max_change_s", 6.0)),
        "measurement": dict(discovery.get("measurement", {})),
        "pressure_policy": dict(discovery.get("pressure_policy", {})),
        "groups": groups,
        "phases": phases,
        "corridor_guards": list(corridor_guards or []),
    }


def load_adaptive_signal_set(path: Path, connection: Any) -> AdaptiveLoadResult:
    with path.open(encoding="utf-8") as source:
        manifest = json.load(source)
    if manifest.get("schema_version") != "1.0":
        raise ValueError("adaptive manifest requires schema_version 1.0")
    if "discovery" not in manifest:
        controllers = manifest.get("controllers")
        if not controllers:
            raise ValueError("adaptive manifest requires controllers")
        ids = [item["traffic_light_id"] for item in controllers]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate traffic light in adaptive manifest")
        return AdaptiveLoadResult(
            str(manifest.get("profile_id", "configured_controllers_only")),
            tuple(AdaptiveSignal(item, connection) for item in controllers),
            {},
        )

    discovery = manifest["discovery"]
    expected = set(discovery.get("expected_controller_ids", []))
    if not expected:
        raise ValueError("discovery manifest requires expected_controller_ids")
    excluded = dict(discovery.get("excluded_controllers", {}))
    if not set(excluded).issubset(expected):
        raise ValueError("excluded controllers must belong to expected_controller_ids")
    actual = set(connection.trafficlight.getIDList())
    corridor_guards = manifest.get("corridor_guards", [])
    if not isinstance(corridor_guards, list):
        raise ValueError("corridor_guards must be a list")
    unknown_guard_sources = {
        guard.get("upstream_traffic_light_id") for guard in corridor_guards
    } - expected
    if unknown_guard_sources:
        raise ValueError("corridor guard upstream controller is not audited")
    signals: list[AdaptiveSignal] = []
    fixed: dict[str, str] = {}
    for traffic_light_id in sorted(expected):
        if traffic_light_id not in actual:
            fixed[traffic_light_id] = "expected controller is absent from the loaded network"
        elif traffic_light_id in excluded:
            fixed[traffic_light_id] = str(excluded[traffic_light_id])
        else:
            try:
                signals.append(AdaptiveSignal(
                    _derive_controller_spec(
                        traffic_light_id,
                        discovery,
                        connection,
                        [
                            guard for guard in corridor_guards
                            if guard.get("upstream_traffic_light_id") == traffic_light_id
                        ],
                    ),
                    connection,
                ))
            except (KeyError, TypeError, ValueError) as exc:
                fixed[traffic_light_id] = f"validation failed: {exc}"
    for traffic_light_id in sorted(actual - expected):
        fixed[traffic_light_id] = "controller is not in the audited network profile"
    if not signals:
        raise ValueError("network adaptive profile has no valid controllers")
    return AdaptiveLoadResult(
        str(manifest.get("profile_id", "network_pressure_v1")),
        tuple(signals), fixed,
    )


def load_adaptive_signals(path: Path, connection: Any) -> list[AdaptiveSignal]:
    """Backward-compatible loader used by existing J3/synthetic callers."""
    return list(load_adaptive_signal_set(path, connection).signals)
