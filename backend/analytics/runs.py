"""Record simulation runs started from the UI (payload schema in docs/DATA_CONTRACTS.md K.5).

:class:`RunRecorder` is fed every snapshot the simulation service already
extracts. It keeps everything in memory and never touches the database;
:func:`save_run` writes the finished payload as one ``runs`` row.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db

SCHEMA_VERSION = "1.0"
SAMPLE_INTERVAL_S = 5.0
QUEUE_MEASUREMENT = "sumo_halting_number"


def utc_now() -> str:
    """ISO 8601 UTC with milliseconds, so ``ended_at`` sorts lexically and rarely ties."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    """A finite number, else ``None`` (unknown stays unknown, never zero)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _count(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def is_green_state(state: Any) -> bool | None:
    """K.2 definition: contains ``G``/``g`` and no ``y``/``Y``; ``None`` if the state is unknown."""
    if not isinstance(state, str) or not state:
        return None
    return ("G" in state or "g" in state) and "y" not in state and "Y" not in state


def sample_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """One timeseries sample from fields the service snapshot already carries."""
    metrics = snapshot.get("metrics") if isinstance(snapshot.get("metrics"), dict) else {}
    network_queue = snapshot.get("network_queue")
    network_queue_vehicles = (
        _count(network_queue.get("vehicles")) if isinstance(network_queue, dict) else None
    )
    if network_queue_vehicles is None:
        network_queue_vehicles = _count(metrics.get("network_queue_vehicles"))
    active = _count(metrics.get("active_vehicle_count"))
    if active is None and isinstance(snapshot.get("vehicles"), list):
        active = len(snapshot["vehicles"])

    controllers = snapshot.get("traffic_light_controllers")
    controllers = controllers if isinstance(controllers, dict) else {}
    approaches = snapshot.get("queue_lengths_by_approach")
    approaches = approaches if isinstance(approaches, dict) else {}
    return {
        "t_s": _number(snapshot.get("simulation_time_s")),
        "network_queue_vehicles": network_queue_vehicles,
        "active_vehicle_count": active,
        "departed_cumulative": _count(metrics.get("departed_vehicle_count")),
        "arrived_cumulative": _count(metrics.get("arrived_vehicle_count")),
        "queue_by_traffic_light": {
            tls_id: _count(item.get("total_queue_vehicles")) if isinstance(item, dict) else None
            for tls_id, item in sorted(controllers.items())
        },
        "queue_by_approach": {
            approach: _count(item.get("vehicles")) if isinstance(item, dict) else None
            for approach, item in sorted(approaches.items())
        },
        "phase_by_traffic_light": {
            tls_id: {
                "phase_index": _count(item.get("current_phase_index")),
                "phase_id": item.get("current_phase_id") if isinstance(item.get("current_phase_id"), str) else None,
            }
            for tls_id, item in sorted(controllers.items())
            if isinstance(item, dict)
        },
    }


@dataclass
class _PhaseTracker:
    """Phase changes of one traffic light, observed at every simulation step."""

    phase_index: int | None
    started_s: float
    green: bool | None
    change_count: int = 0
    green_durations_s: list[float] = field(default_factory=list)
    green_unknown: bool = False

    def observe(self, phase_index: int | None, state: Any, t_s: float) -> None:
        if phase_index is None or phase_index == self.phase_index:
            return
        if self.phase_index is not None:
            self.change_count += 1
            if self.green is None:
                self.green_unknown = True
            elif self.green:
                self.green_durations_s.append(t_s - self.started_s)
        self.phase_index, self.started_s, self.green = phase_index, t_s, is_green_state(state)

    def summary(self, tls_id: str) -> dict[str, Any]:
        durations = self.green_durations_s
        return {
            "traffic_light_id": tls_id,
            "phase_change_count": self.change_count,
            "completed_green_phases": len(durations),
            "mean_green_duration_s": (
                None if self.green_unknown or not durations else sum(durations) / len(durations)
            ),
        }


def summarize_intersections(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mean/max ``queue_by_traffic_light`` over the samples; ``None`` without known values."""
    values: dict[str, list[int]] = {}
    for sample in samples:
        for tls_id, queue in (sample.get("queue_by_traffic_light") or {}).items():
            bucket = values.setdefault(tls_id, [])
            if queue is not None:
                bucket.append(queue)
    return [
        {
            "traffic_light_id": tls_id,
            "mean_queue_vehicles": sum(known) / len(known) if known else None,
            "max_queue_vehicles": max(known) if known else None,
            "sample_count": len(known),
        }
        for tls_id, known in sorted(values.items())
    ]


def build_payload(
    *,
    run: dict[str, Any],
    summary: dict[str, Any] | None,
    samples: list[dict[str, Any]],
    phases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the stored document. Pure: no clock, no I/O."""
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "simulation_run",
        "run": dict(run),
        "summary": copy.deepcopy(summary) if isinstance(summary, dict) else None,
        "timeseries": {
            "interval_s": SAMPLE_INTERVAL_S,
            "queue_measurement": QUEUE_MEASUREMENT,
            "samples": list(samples),
        },
        "intersections": summarize_intersections(samples),
        "phases": sorted(phases, key=lambda item: item["traffic_light_id"]),
    }


class RunRecorder:
    """In-memory accumulation for one run; owned by the simulation worker thread."""

    def __init__(
        self, *, run_id: str, scenario_id: str, control_mode: str,
        initial_snapshot: dict[str, Any], started_at: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.scenario_id = scenario_id
        self.control_mode = control_mode
        self.started_at = started_at or utc_now()
        self.legacy_scenario_id = initial_snapshot.get("scenario_id")
        self.sim_start_s = _number(initial_snapshot.get("simulation_time_s"))
        self.samples: list[dict[str, Any]] = []
        self._next_sample_s = None if self.sim_start_s is None else self.sim_start_s + SAMPLE_INTERVAL_S
        self._phases: dict[str, _PhaseTracker] = {}
        self._last_snapshot = initial_snapshot
        self._track_phases(initial_snapshot)

    def _track_phases(self, snapshot: dict[str, Any]) -> None:
        t_s = _number(snapshot.get("simulation_time_s"))
        controllers = snapshot.get("traffic_light_controllers")
        if t_s is None or not isinstance(controllers, dict):
            return
        for tls_id, item in controllers.items():
            if not isinstance(item, dict):
                continue
            phase_index = _count(item.get("current_phase_index"))
            state = item.get("traffic_light_state")
            tracker = self._phases.get(tls_id)
            if tracker is None:
                if phase_index is not None:
                    self._phases[tls_id] = _PhaseTracker(phase_index, t_s, is_green_state(state))
            else:
                tracker.observe(phase_index, state, t_s)

    def observe(self, snapshot: dict[str, Any]) -> None:
        """Call once per extracted snapshot; samples every ``SAMPLE_INTERVAL_S`` of simulation time."""
        self._last_snapshot = snapshot
        self._track_phases(snapshot)
        t_s = _number(snapshot.get("simulation_time_s"))
        if t_s is None or self._next_sample_s is None or t_s < self._next_sample_s:
            return
        self.samples.append(sample_from_snapshot(snapshot))
        while self._next_sample_s <= t_s:
            self._next_sample_s += SAMPLE_INTERVAL_S

    def finish(self, status: str, *, ended_at: str | None = None, error: str | None = None) -> dict[str, Any]:
        sim_end_s = _number(self._last_snapshot.get("simulation_time_s"))
        duration = (
            sim_end_s - self.sim_start_s
            if sim_end_s is not None and self.sim_start_s is not None
            else None
        )
        run = {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "legacy_scenario_id": self.legacy_scenario_id,
            "control_mode": self.control_mode,
            "status": status,
            "started_at": self.started_at,
            "ended_at": ended_at or utc_now(),
            "sim_start_s": self.sim_start_s,
            "sim_end_s": sim_end_s,
            "sim_duration_s": duration,
            "sample_count": len(self.samples),
            "error": error,
        }
        return build_payload(
            run=run,
            summary=self._last_snapshot.get("metrics"),
            samples=self.samples,
            phases=[tracker.summary(tls_id) for tls_id, tracker in self._phases.items()],
        )


def save_run(payload: dict[str, Any], path: str | Path | None = None) -> None:
    """Write one ``runs`` row (creates the database file and tables if missing)."""
    run = payload["run"]
    db.insert_run(
        run_id=run["run_id"],
        scenario_id=run["scenario_id"],
        control_mode=run["control_mode"],
        status=run["status"],
        started_at=run["started_at"],
        ended_at=run["ended_at"],
        sim_duration_s=run["sim_duration_s"],
        payload=json.dumps(payload, allow_nan=False, separators=(",", ":")),
        path=path,
    )
