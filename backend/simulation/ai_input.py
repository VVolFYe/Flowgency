"""Validate and inspect prerecorded vision JSONL as a video-time timeline."""

from __future__ import annotations

import argparse
import bisect
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, TypeVar

from pydantic import BaseModel, ValidationError

from backend.models.gates import Arm, GateCounts, GateEvent


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAPPING_PATH = (
    REPOSITORY_ROOT / "scenarios" / "single_intersection" / "ai_arm_mapping.json"
)
DEFAULT_SCENARIO_MAPPING_PATH = (
    REPOSITORY_ROOT / "scenarios" / "single_intersection" / "mappings.json"
)
ARMS = ("north", "east", "south", "west")
ModelT = TypeVar("ModelT", bound=BaseModel)


class JsonlValidationError(ValueError):
    """A JSONL record or cross-record invariant is invalid."""


@dataclass(frozen=True)
class ArmMapping:
    camera_arm: str
    sumo_incoming_edge_id: str
    orientation_status: str


@dataclass(frozen=True)
class ArmTimelineState:
    sumo_incoming_edge_id: str
    observed_vehicles: int | None
    new_arrival_count: int
    new_arrival_track_ids: tuple[int, ...]
    entered_total: int | None
    discharged_total: int | None


@dataclass(frozen=True)
class TimelinePoint:
    t_s: float
    interval_end_s: float
    approaches: dict[str, ArmTimelineState]
    in_intersection: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ObservationTimeline:
    points: tuple[TimelinePoint, ...]
    mapping: dict[str, ArmMapping]
    model_ids: tuple[str, ...]

    @property
    def recording_end_s(self) -> float:
        return self.points[-1].interval_end_s

    def at_second(self, t_s: float) -> TimelinePoint:
        for point in self.points:
            if point.t_s == t_s:
                return point
        raise KeyError(f"no count observation exists at video time {t_s:g}s")

    def summary(self) -> dict[str, Any]:
        first = self.points[0]
        last = self.points[-1]
        return {
            "schema_version": "1.0",
            "observation_count": len(self.points),
            "first_observation_t_s": first.t_s,
            "last_observation_t_s": last.t_s,
            "recording_end_s": self.recording_end_s,
            "model_ids": list(self.model_ids),
            "orientation_status": sorted({item.orientation_status for item in self.mapping.values()}),
            "initial_observed_vehicles": {
                arm: state.observed_vehicles for arm, state in first.approaches.items()
            },
            "new_arrivals": {
                arm: sum(point.approaches[arm].new_arrival_count for point in self.points)
                for arm in self.mapping
            },
            "final_cumulative": {
                arm: {
                    "entered_total": last.approaches[arm].entered_total,
                    "discharged_total": last.approaches[arm].discharged_total,
                    "observed_vehicles": last.approaches[arm].observed_vehicles,
                }
                for arm in self.mapping
            },
            "initial_in_intersection": first.in_intersection,
            "final_in_intersection": last.in_intersection,
        }


def read_jsonl(path: Path, model: type[ModelT]) -> list[ModelT]:
    """Read one model per non-empty line with useful file/line errors."""
    records: list[ModelT] = []
    try:
        source = path.open(encoding="utf-8")
    except OSError as exc:
        raise FileNotFoundError(f"JSONL input not found: {path}") from exc
    with source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                records.append(model.model_validate(payload))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise JsonlValidationError(f"{path}:{line_number}: {exc}") from exc
    if not records:
        raise JsonlValidationError(f"{path}: contains no records")
    return records


def load_arm_mapping(
    mapping_path: Path = DEFAULT_MAPPING_PATH,
    scenario_mapping_path: Path = DEFAULT_SCENARIO_MAPPING_PATH,
) -> dict[str, ArmMapping]:
    """Load camera-arm mapping and verify every edge against the SUMO mapping."""
    try:
        config = json.loads(mapping_path.read_text(encoding="utf-8"))
        scenario = json.loads(scenario_mapping_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JsonlValidationError(f"could not load arm mapping: {exc}") from exc
    if config.get("schema_version") != "1.0":
        raise JsonlValidationError("arm mapping schema_version must be 1.0")
    if config.get("scenario_id") != scenario.get("scenario_id"):
        raise JsonlValidationError("arm mapping scenario_id does not match mappings.json")
    configured = config.get("arms")
    if not isinstance(configured, dict) or set(configured) != set(ARMS):
        raise JsonlValidationError("arm mapping must explicitly define north/east/south/west")
    valid_edges = set(scenario.get("incoming_edges", {}).values())
    result: dict[str, ArmMapping] = {}
    for arm in ARMS:
        item = configured[arm]
        if not isinstance(item, dict):
            raise JsonlValidationError(f"mapping for {arm} must be an object")
        edge = item.get("sumo_incoming_edge_id")
        status = item.get("orientation_status")
        if edge not in valid_edges:
            raise JsonlValidationError(f"camera arm {arm} maps to unknown incoming edge {edge!r}")
        if status != "unverified_camera_to_sumo":
            raise JsonlValidationError(f"camera arm {arm} must explicitly remain orientation-unverified")
        result[arm] = ArmMapping(arm, edge, status)
    if len({item.sumo_incoming_edge_id for item in result.values()}) != len(result):
        raise JsonlValidationError("camera arms must map one-to-one to synthetic incoming edges")
    return result


def _require_ordered(records: Iterable[GateCounts | GateEvent], label: str) -> None:
    previous = -1.0
    for record in records:
        if record.t_s < previous:
            raise JsonlValidationError(f"{label} records are not ordered by video time")
        previous = record.t_s


def build_timeline(
    counts_path: Path,
    events_path: Path,
    mapping_path: Path = DEFAULT_MAPPING_PATH,
    scenario_mapping_path: Path = DEFAULT_SCENARIO_MAPPING_PATH,
) -> ObservationTimeline:
    """Build count observations plus event-derived arrivals in video-time intervals."""
    counts = read_jsonl(counts_path, GateCounts)
    events = read_jsonl(events_path, GateEvent)
    mapping = load_arm_mapping(mapping_path, scenario_mapping_path)
    _require_ordered(counts, "count")
    _require_ordered(events, "event")
    times = [item.t_s for item in counts]
    if len(set(times)) != len(times):
        raise JsonlValidationError("count observations contain duplicate timestamps")
    if len(times) == 1:
        cadence = 1.0
    else:
        deltas = [following - current for current, following in zip(times, times[1:])]
        cadence = min(deltas)
        if cadence <= 0:
            raise JsonlValidationError("count observation timestamps must increase")
    recording_end = times[-1] + cadence
    arrivals: list[dict[str, list[int]]] = [
        {arm: [] for arm in mapping} for _ in counts
    ]
    seen_arrivals: set[int] = set()
    for event in events:
        if event.event != "approach_entered":
            continue
        if event.track_id in seen_arrivals:
            raise JsonlValidationError(
                f"duplicate approach_entered event for track_id {event.track_id}"
            )
        seen_arrivals.add(event.track_id)
        index = bisect.bisect_right(times, event.t_s) - 1
        if index < 0 or event.t_s >= recording_end:
            raise JsonlValidationError(
                f"approach arrival at {event.t_s:g}s is outside the recording timeline"
            )
        arrivals[index][event.arm].append(event.track_id)

    previous_totals: dict[str, tuple[int, int]] = {}
    points: list[TimelinePoint] = []
    for index, observation in enumerate(counts):
        unknown_arms = set(observation.approaches) - set(mapping)
        if unknown_arms:
            raise JsonlValidationError(f"count observation has unmapped arms: {sorted(unknown_arms)}")
        approaches: dict[str, ArmTimelineState] = {}
        for arm in mapping:
            count = observation.approaches.get(arm)  # absent means unknown, never zero
            track_ids = tuple(arrivals[index][arm])
            if count is not None:
                previous_entered, previous_discharged = previous_totals.get(arm, (0, 0))
                if (
                    count.entered_total < previous_entered
                    or count.discharged_total < previous_discharged
                ):
                    raise JsonlValidationError(f"cumulative totals decreased for camera arm {arm}")
                previous_totals[arm] = (count.entered_total, count.discharged_total)
            approaches[arm] = ArmTimelineState(
                sumo_incoming_edge_id=mapping[arm].sumo_incoming_edge_id,
                observed_vehicles=count.vehicles_on_approach if count is not None else None,
                new_arrival_count=len(track_ids),
                new_arrival_track_ids=track_ids,
                entered_total=count.entered_total if count is not None else None,
                discharged_total=count.discharged_total if count is not None else None,
            )
        points.append(TimelinePoint(
            t_s=observation.t_s,
            interval_end_s=times[index + 1] if index + 1 < len(times) else recording_end,
            approaches=approaches,
            in_intersection=observation.in_intersection,
        ))
    model_ids = tuple(sorted({item.model_id for item in (*counts, *events)}))
    return ObservationTimeline(tuple(points), mapping, model_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING_PATH)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--second", type=float, help="print the exact count observation at video second")
    selection.add_argument("--summary", action="store_true", help="print recording summary (default)")
    args = parser.parse_args()
    try:
        timeline = build_timeline(args.counts, args.events, args.mapping)
        output = timeline.at_second(args.second).to_dict() if args.second is not None else timeline.summary()
    except (FileNotFoundError, JsonlValidationError, KeyError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
