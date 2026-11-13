"""Verified TraCI adapter for the reusable cycle planner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.controller.cycle_planner import CycleConfig, FixedPhase, GreenGroup, plan_cycle


class AdaptiveSignal:
    """Own one TLS; change only green dwell at phase entry, never signal states."""

    def __init__(self, specification: dict[str, Any], connection: Any) -> None:
        self.spec = specification
        self.connection = connection
        self.tls_id = specification["traffic_light_id"]
        self.phases = specification["phases"]
        self.groups = specification["groups"]
        self._phase_seen: int | None = None
        self._plan = None
        self._lanes: dict[str, tuple[str, ...]] = {}
        self._validate_program()

    def _validate_program(self) -> None:
        light = self.connection.trafficlight
        if self.tls_id not in light.getIDList():
            raise ValueError(f"unknown traffic light {self.tls_id}")
        if light.getProgram(self.tls_id) != self.spec["program_id"]:
            raise ValueError(f"unexpected program for {self.tls_id}")
        logics = [logic for logic in light.getAllProgramLogics(self.tls_id) if logic.programID == self.spec["program_id"]]
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
            lanes = {link[0] for i in indices for link in links[i]}
            if not lanes:
                raise ValueError("group has no controlled incoming lanes")
            self._lanes[group["group_id"]] = tuple(sorted(lanes))
            own = next(phase for phase in self.phases if phase.get("group_id") == group["group_id"])
            if group["phase_index"] != own["index"]:
                raise ValueError("group phase index differs from audited phase")
            for i in indices:
                if own["state"][i] not in "Gg":
                    raise ValueError("group link is not green in its configured phase")
                if any(phase["state"][i] not in "rR" for phase in self.phases if phase.get("group_id") not in (None, group["group_id"])):
                    raise ValueError("group link is active in another group's green")
        if any(set(a).intersection(b) for n, a in enumerate(self._lanes.values()) for b in list(self._lanes.values())[n + 1:]):
            raise ValueError("incoming lane belongs to multiple groups")

    def tick(self) -> dict[str, Any] | None:
        """Call after each simulation step; returns a new cycle plan when made."""
        light = self.connection.trafficlight
        phase_index = int(light.getPhase(self.tls_id))
        if self._phase_seen is None and phase_index != 0:
            return None  # wait for a complete cycle boundary
        if phase_index == self._phase_seen:
            return None
        if phase_index != (0 if self._phase_seen is None else (self._phase_seen + 1) % len(self.phases)):
            raise RuntimeError(f"unexpected phase transition for {self.tls_id}")
        if light.getRedYellowGreenState(self.tls_id) != self.phases[phase_index]["state"]:
            raise RuntimeError(f"unexpected signal state for {self.tls_id}")
        self._phase_seen = phase_index
        phase = self.phases[phase_index]
        if phase_index == 0:
            queues = {
                group_id: sum(int(self.connection.lane.getLastStepHaltingNumber(lane)) for lane in lanes)
                for group_id, lanes in self._lanes.items()
            }
            config = CycleConfig(
                intersection_id=self.spec["intersection_id"],
                groups=tuple(GreenGroup(g["group_id"], f"phase_{g['phase_index']}", g["min_green_s"], g["max_green_s"]) for g in self.groups),
                fixed_phases=tuple(FixedPhase(f"phase_{p['index']}", p["duration_s"]) for p in self.phases if "group_id" not in p),
                green_budget_s=self.spec["green_budget_s"],
                phase_order=tuple(f"phase_{p['index']}" for p in self.phases),
                max_change_s=self.spec.get("max_change_s", 12.0),
            )
            baseline = {g["group_id"]: self.phases[g["phase_index"]]["duration_s"] for g in self.groups}
            previous = baseline if self._plan is None else self._plan.green_durations_s
            self._plan = plan_cycle(config, queues, previous)
        if "group_id" in phase and self._plan is not None:
            light.setPhaseDuration(self.tls_id, self._plan.green_durations_s[phase["group_id"]])
        if phase_index == 0 and self._plan is not None:
            return {"intersection_id": self.spec["intersection_id"], "queues": self._plan.measured_queues,
                    "green_durations_s": self._plan.green_durations_s, "reason": self._plan.reason}
        return None


def load_adaptive_signals(path: Path, connection: Any) -> list[AdaptiveSignal]:
    with path.open(encoding="utf-8") as source:
        manifest = json.load(source)
    if manifest.get("schema_version") != "1.0" or not manifest.get("controllers"):
        raise ValueError("adaptive manifest requires schema_version 1.0 and controllers")
    ids = [item["traffic_light_id"] for item in manifest["controllers"]]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate traffic light in adaptive manifest")
    return [AdaptiveSignal(item, connection) for item in manifest["controllers"]]
