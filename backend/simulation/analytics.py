"""Aggregation helpers for the static fixed-vs-adaptive analytics export.

The pure functions here turn per-step samples and tripinfo records into the
``frontend/public/analytics/<id>.json`` sections. ``StepSampler`` is the only
TraCI-facing part; ``cycle_run`` uses it when ``--analytics-samples`` is given.
Unknown values stay ``None``; they are never replaced by zero.
"""

from __future__ import annotations

import bisect
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

SAMPLES_SCHEMA_VERSION = "1.0"
QUEUE_MEASUREMENT = "sumo_halting_number_unique_controlled_lanes"
DEFAULT_INTERVAL_S = 10.0
MAX_TIMESERIES_SAMPLES = 600
HISTOGRAM_TARGET_BINS = 20


def is_green_state(state: str) -> bool:
    """A phase counts as green when it releases a movement and none is amber."""
    return any(char in "Gg" for char in state) and not any(char in "yY" for char in state)


class StepSampler:
    """Record network and per-controller halting counts once per SUMO step."""

    def __init__(self, connection: Any) -> None:
        light = connection.trafficlight
        self._connection = connection
        self.traffic_light_ids = sorted(light.getIDList())
        self._lanes = {
            tls_id: sorted(set(light.getControlledLanes(tls_id)))
            for tls_id in self.traffic_light_ids
        }
        self._network_lanes = sorted({lane for lanes in self._lanes.values() for lane in lanes})
        now = float(connection.simulation.getTime())
        self._phase = {tls_id: int(light.getPhase(tls_id)) for tls_id in self.traffic_light_ids}
        self._phase_state = {
            tls_id: str(light.getRedYellowGreenState(tls_id)) for tls_id in self.traffic_light_ids
        }
        self._phase_started = {tls_id: now for tls_id in self.traffic_light_ids}
        self.green_phase_durations_s: dict[str, list[float]] = {
            tls_id: [] for tls_id in self.traffic_light_ids
        }
        self.steps: list[dict[str, Any]] = []

    def record(self, *, arrived_cumulative: int) -> None:
        connection = self._connection
        lane = connection.lane
        light = connection.trafficlight
        now = float(connection.simulation.getTime())
        halting = {lane_id: int(lane.getLastStepHaltingNumber(lane_id)) for lane_id in self._network_lanes}
        for tls_id in self.traffic_light_ids:
            phase = int(light.getPhase(tls_id))
            if phase != self._phase[tls_id]:
                if is_green_state(self._phase_state[tls_id]):
                    self.green_phase_durations_s[tls_id].append(now - self._phase_started[tls_id])
                self._phase[tls_id] = phase
                self._phase_state[tls_id] = str(light.getRedYellowGreenState(tls_id))
                self._phase_started[tls_id] = now
        self.steps.append({
            "t_s": now,
            "network_queue_vehicles": sum(halting.values()),
            "active_vehicles": int(connection.vehicle.getIDCount()),
            "arrived_cumulative": int(arrived_cumulative),
            "tls_queue_vehicles": [
                sum(halting[lane_id] for lane_id in self._lanes[tls_id])
                for tls_id in self.traffic_light_ids
            ],
        })

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SAMPLES_SCHEMA_VERSION,
            "queue_measurement": QUEUE_MEASUREMENT,
            "green_phase_definition": "completed phases with a G/g and no y/Y signal",
            "traffic_light_ids": self.traffic_light_ids,
            "steps": self.steps,
            "green_phase_durations_s": self.green_phase_durations_s,
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json()) + "\n", encoding="utf-8")


def read_samples(path: Path) -> dict[str, Any] | None:
    """Return per-step samples, or ``None`` when the run did not produce them."""
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SAMPLES_SCHEMA_VERSION:
        raise ValueError(f"unsupported analytics samples schema in {path}")
    return data


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolation percentile (NumPy's default method); ``q`` in [0, 1]."""
    if not values:
        return None
    if not 0.0 <= q <= 1.0:
        raise ValueError("percentile q must be within [0, 1]")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def shared_bin_edges(
    value_lists: Iterable[Sequence[float] | None], target_bins: int = HISTOGRAM_TARGET_BINS
) -> list[float] | None:
    """Equal-width edges from 0 with a 1/2/2.5/5 x 10^k width covering every value."""
    values = [value for values in value_lists if values for value in values]
    if not values:
        return None
    if min(values) < 0:
        raise ValueError("histogram values must be nonnegative")
    largest = max(values)
    if largest == 0:
        return [0.0, 1.0]
    raw = largest / target_bins
    magnitude = 10 ** math.floor(math.log10(raw))
    width = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    bins = math.floor(largest / width) + 1  # the largest value falls strictly inside the last bin
    return [round(index * width, 6) for index in range(bins + 1)]


def histogram(values: Sequence[float], edges: Sequence[float]) -> list[int]:
    """Counts per ``[edge_i, edge_i+1)`` bin; the last bin also includes its upper edge."""
    counts = [0] * (len(edges) - 1)
    for value in values:
        index = bisect.bisect_right(edges, value) - 1
        counts[min(max(index, 0), len(counts) - 1)] += 1
    return counts


def distribution(
    values_by_mode: dict[str, Sequence[float] | None], modes: Sequence[str]
) -> dict[str, Any]:
    edges = shared_bin_edges(values_by_mode.get(mode) for mode in modes)
    result: dict[str, Any] = {"bin_edges": edges}
    for mode in modes:
        values = values_by_mode.get(mode)
        if values is None:
            result[mode] = None
            continue
        result[mode] = {
            "count": len(values),
            "p50": _round(percentile(values, 0.50)),
            "p90": _round(percentile(values, 0.90)),
            "p95": _round(percentile(values, 0.95)),
            "max": _round(max(values)) if values else None,
            "histogram": histogram(values, edges) if edges is not None else [],
        }
    return result


def timeseries_interval(
    durations_s: Iterable[float], base_interval_s: float = DEFAULT_INTERVAL_S,
    max_samples: int = MAX_TIMESERIES_SAMPLES,
) -> float:
    """Smallest base_interval * 2^k that keeps every mode under ``max_samples``."""
    interval = base_interval_s
    longest = max(durations_s, default=0.0)
    while longest / interval > max_samples:
        interval *= 2
    return interval


def downsample(steps: Sequence[dict[str, Any]], interval_s: float) -> list[dict[str, Any]]:
    """Keep the first step at or after each interval boundary, plus the final step."""
    rows: list[dict[str, Any]] = []
    boundary = interval_s
    for step in steps:
        if step["t_s"] + 1e-9 >= boundary:
            rows.append(step)
            while boundary <= step["t_s"] + 1e-9:
                boundary += interval_s
    if steps and (not rows or rows[-1] is not steps[-1]):
        rows.append(steps[-1])
    return [
        {
            "t_s": round(row["t_s"], 3),
            "network_queue_vehicles": row["network_queue_vehicles"],
            "active_vehicles": row["active_vehicles"],
            "arrived_cumulative": row["arrived_cumulative"],
        }
        for row in rows
    ]


def network_queue_stats(samples: dict[str, Any] | None) -> dict[str, float | int | None]:
    queues = [step["network_queue_vehicles"] for step in samples["steps"]] if samples else []
    return {
        "mean": _round(mean(queues)),
        "max": max(queues) if queues else None,
    }


def intersection_stats(
    samples: dict[str, Any] | None, decision_events: Sequence[dict[str, Any]] | None
) -> dict[str, dict[str, Any]] | None:
    if samples is None:
        return None
    decisions: dict[str, int] = {}
    for event in decision_events or []:
        tls_id = event.get("traffic_light_id")
        if tls_id is not None:
            decisions[tls_id] = decisions.get(tls_id, 0) + 1
    result: dict[str, dict[str, Any]] = {}
    for index, tls_id in enumerate(samples["traffic_light_ids"]):
        queues = [step["tls_queue_vehicles"][index] for step in samples["steps"]]
        greens = samples["green_phase_durations_s"].get(tls_id, [])
        result[tls_id] = {
            "mean_queue": _round(mean(queues)),
            "max_queue": max(queues) if queues else None,
            "mean_green_s": _round(mean(greens)),
            "completed_green_phases": len(greens),
            "decision_count": decisions.get(tls_id, 0) if decision_events is not None else None,
        }
    return result


def throughput_vehicles_per_hour(
    records: Sequence[dict[str, Any]] | None, begin_s: float
) -> float | None:
    """Completed trips per hour between scenario begin and the last arrival."""
    if not records:
        return None
    arrivals = [record.get("arrival_s") for record in records]
    if any(arrival is None for arrival in arrivals):
        return None
    elapsed = max(arrivals) - begin_s
    return round(len(records) * 3600.0 / elapsed, 3) if elapsed > 0 else None


def emergency_stats(
    records: Sequence[dict[str, Any]] | None, emergency_types: frozenset[str]
) -> dict[str, Any] | None:
    """Emergency vs normal time loss; ``None`` when trips or vehicle types are unknown."""
    if records is None or any(record.get("vehicle_type") is None for record in records):
        return None
    emergency = [r["time_loss_s"] for r in records if r["vehicle_type"] in emergency_types]
    normal = [r["time_loss_s"] for r in records if r["vehicle_type"] not in emergency_types]
    return {
        "emergency_trip_count": len(emergency),
        "normal_trip_count": len(normal),
        "emergency_average_time_loss_s": _round(mean(emergency)),
        "normal_average_time_loss_s": _round(mean(normal)),
    }


def paired(fixed: float | None, adaptive: float | None, better: str = "lower") -> dict[str, Any]:
    """Existing benchmark convention: positive improvement favours adaptive."""
    if better not in {"lower", "higher"}:
        raise ValueError("better must be 'lower' or 'higher'")
    improvement = None
    percentage = None
    if fixed is not None and adaptive is not None:
        improvement = fixed - adaptive if better == "lower" else adaptive - fixed
        percentage = round(100 * improvement / fixed, 2) if fixed else None
        improvement = round(improvement, 3)
    return {
        "fixed": fixed,
        "adaptive": adaptive,
        "absolute_improvement": improvement,
        "percentage_improvement": percentage,
        "better": better,
    }
