"""Export gate-mode ``counts.jsonl`` + ``events.jsonl`` to a static analytics JSON.

Reads the contracts in docs/DATA_CONTRACTS.md sections I and J and writes the
vision analytics file consumed by the frontend statistics page::

    python -m backend.vision.export_analytics \
        --index frontend/public/analytics/index.json

No CV stack and no SUMO: stdlib plus the shared pydantic gate models.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, get_args

from backend.models.analytics_index import upsert_index_entry
from backend.models.gates import Arm, GateCounts, GateEvent

SCHEMA_VERSION = "1.0"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE = REPOSITORY_ROOT / "backend" / "vision" / "samples" / "youtube_full"
DEFAULT_OUT = REPOSITORY_ROOT / "frontend" / "public" / "analytics" / "youtube.json"
DEFAULT_LABEL = "YouTube top-down intersection"
ARMS: tuple[str, ...] = get_args(Arm)
UNKNOWN_ORIGIN = "unknown"
FLOW_WINDOW_S = 60


def _repository_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def read_jsonl(path: Path, model: type[GateCounts] | type[GateEvent]) -> list[Any]:
    """Parse and validate every non-empty line against its contract model."""
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                rows.append(model.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
    return rows


def _single_model_id(counts: list[GateCounts], events: list[GateEvent]) -> str:
    model_ids = {row.model_id for row in counts} | {event.model_id for event in events}
    if len(model_ids) != 1:
        raise ValueError(f"expected one model_id across counts and events, got {sorted(model_ids)}")
    return model_ids.pop()


def _fps(events: list[GateEvent]) -> float | None:
    """Frame rate implied by the latest event (``t_s = frame / fps``); None without events."""
    timed = [event for event in events if event.t_s > 0 and event.frame > 0]
    if not timed:
        return None
    latest = max(timed, key=lambda event: event.frame)
    return round(latest.frame / latest.t_s, 3)


def _arm_value(row: GateCounts, arm: str, field: str) -> int | None:
    approach = row.approaches.get(arm)
    return getattr(approach, field) if approach is not None else None


def flow_per_minute(counts: list[GateCounts], arms: list[str]) -> list[dict[str, Any]]:
    """Per-window differences of the cumulative totals; the last window may be partial.

    Window ``m`` covers ``(60 m, 60 (m + 1)]`` seconds of video. The first window
    starts from zero because the totals count triggers since the start of the video.
    """
    by_second = {row.t_s: row for row in counts}
    last_t = counts[-1].t_s
    windows = []
    for index in range(max(1, math.ceil(last_t / FLOW_WINDOW_S))):
        start = index * FLOW_WINDOW_S
        end = min(start + FLOW_WINDOW_S, last_t)
        start_row = by_second.get(float(start)) if index else None
        end_row = by_second.get(float(end))
        window: dict[str, Any] = {
            "start_s": float(start), "end_s": float(end),
            "partial": end - start < FLOW_WINDOW_S,
            "entered": {}, "discharged": {},
        }
        for key, field in (("entered", "entered_total"), ("discharged", "discharged_total")):
            for arm in arms:
                after = _arm_value(end_row, arm, field) if end_row is not None else None
                before = 0 if index == 0 else (
                    _arm_value(start_row, arm, field) if start_row is not None else None
                )
                window[key][arm] = after - before if after is not None and before is not None else None
        windows.append(window)
    return windows


def turning_matrix(events: list[GateEvent], arms: list[str]) -> dict[str, Any]:
    origins = [*arms, UNKNOWN_ORIGIN]
    matrix = {origin: {arm: 0 for arm in arms} for origin in origins}
    exits = [event for event in events if event.event == "intersection_exited"]
    for event in exits:
        origin = event.origin_arm if event.origin_arm is not None else UNKNOWN_ORIGIN
        matrix.setdefault(origin, {arm: 0 for arm in arms})
        matrix[origin][event.arm] = matrix[origin].get(event.arm, 0) + 1
    return {
        "origins": origins,
        "exits": list(arms),
        "counts": matrix,
        "total_exits": len(exits),
        "unknown_origin_exits": sum(matrix[UNKNOWN_ORIGIN].values()),
    }


def build_vision_analytics(
    counts: list[GateCounts], events: list[GateEvent], *, label: str,
    counts_path: Path, events_path: Path,
) -> dict[str, Any]:
    if not counts:
        raise ValueError("counts.jsonl has no lines")
    counts = sorted(counts, key=lambda row: row.t_s)
    arms = [arm for arm in ARMS if any(arm in row.approaches for row in counts)]
    model_id = _single_model_id(counts, events)
    readme = counts_path.parent / "README.md"

    on_approach = {arm: [_arm_value(row, arm, "vehicles_on_approach") for row in counts] for arm in arms}
    last = counts[-1]
    totals = {}
    for arm in arms:
        observed = [value for value in on_approach[arm] if value is not None]
        totals[arm] = {
            "entered": _arm_value(last, arm, "entered_total"),
            "discharged": _arm_value(last, arm, "discharged_total"),
            "peak_vehicles_on_approach": max(observed) if observed else None,
        }
    turning = turning_matrix(events, arms)
    initial = ", ".join(
        f"{arm} {_arm_value(counts[0], arm, 'vehicles_on_approach')}" for arm in arms
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "vision",
        "source": {
            "label": label,
            "duration_s": last.t_s,
            "duration_definition": "last whole second covered by counts.jsonl",
            "fps": _fps(events),
            "model_id": model_id,
            "sample_readme": _repository_path(readme) if readme.is_file() else None,
            "counts_path": _repository_path(counts_path),
            "events_path": _repository_path(events_path),
            "video_in_repository": False,
        },
        "arms": arms,
        "timeseries": {
            "t_s": [row.t_s for row in counts],
            "vehicles_on_approach": on_approach,
            "in_intersection": [row.in_intersection for row in counts],
        },
        "flow_per_minute": flow_per_minute(counts, arms),
        "totals": totals,
        "turning_matrix": turning,
        "limitations": [
            "vehicles_on_approach includes vehicles already on each approach in the first 0.5 s "
            f"(t_s = 0: {initial}); entered/discharged totals do not count them, so the series "
            "and the totals are offset by that initial count.",
            f"The clip is a top-down (drone) view processed with the team-trained VisDrone "
            f"detector ({model_id}); the street-camera COCO model does not apply.",
            "Counts are camera-derived estimates that can drift over the clip (missed detections, "
            "broken or duplicate tracks, gate placement); they are not SUMO queue lengths, and "
            "vehicles_on_approach includes moving as well as queued vehicles.",
            "Arms are named by the side of the camera image (north = top edge), not by compass "
            "bearing, and are not mapped to SUMO approaches.",
            f"{turning['unknown_origin_exits']} of {turning['total_exits']} exits have no known "
            "origin (already in the junction at the start, or no entry seen for the track) and "
            "are counted under 'unknown'.",
            "The demo video itself is not stored in git.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--counts", type=Path, default=DEFAULT_SAMPLE / "counts.jsonl")
    parser.add_argument("--events", type=Path, default=DEFAULT_SAMPLE / "events.jsonl")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--index", type=Path, help="register --out in this index.json")
    args = parser.parse_args(argv)
    counts = read_jsonl(args.counts, GateCounts)
    events = read_jsonl(args.events, GateEvent)
    document = build_vision_analytics(
        counts, events, label=args.label, counts_path=args.counts, events_path=args.events
    )
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    print(f"vision analytics written to {out} ({out.stat().st_size} bytes)")
    if args.index is not None:
        upsert_index_entry(args.index, entry_id=out.stem, label=args.label, kind="vision", file_path=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
