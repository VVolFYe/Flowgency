"""Gate mode: per-frame detections -> vehicle tracks -> gate events and counts files.

Detections are ``x1, y1, x2, y2, score, cls`` rows in the detector's own class
indices. Each frame: keep the profile's vehicle classes and merge them into
``vehicle``, class-agnostic NMS (incl. nested boxes), drop scores below the
profile's ``conf``, run Ultralytics ByteTrack (stock ``bytetrack.yaml``), map
duplicate track IDs (:class:`DuplicateTrackFilter`), and reduce each box to the
scene's counting point. No YOLO model is loaded here.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from backend.models.gates import GateCounts, GateEvent

from .counting import TrackedBox
from .detections import merge_vehicle_classes
from .gates import GateRun, TrackPoint, run_gates
from .geometry import Point, point_in_polygon
from .scene import SceneConfig
from .track_filter import DuplicateTrackFilter

TRACKER_CONFIG = "bytetrack.yaml"


@dataclass(frozen=True)
class TrackedFrame:
    frame: int
    boxes: tuple[TrackedBox, ...]

    def points(self, counting_point: str) -> list[TrackPoint]:
        return [TrackPoint(b.track_id, b.point(counting_point)) for b in self.boxes]


class GateTracker:
    """ByteTrack over merged single-class detections; feed frames in order."""

    def __init__(self, frame_size: tuple[int, int], class_ids: Sequence[int], conf: float) -> None:
        from ultralytics.trackers.byte_tracker import BYTETracker
        from ultralytics.utils import YAML, IterableSimpleNamespace
        from ultralytics.utils.checks import check_yaml

        if not 0.0 < conf < 1.0:
            raise ValueError("conf must be in (0, 1)")
        self.width, self.height = frame_size
        self.class_ids = list(class_ids)
        self.conf = conf
        cfg = IterableSimpleNamespace(**YAML.load(check_yaml(TRACKER_CONFIG)))
        self._tracker = BYTETracker(args=cfg)
        self._dedupe = DuplicateTrackFilter()

    def update(self, frame: int, dets: np.ndarray) -> TrackedFrame:
        from ultralytics.engine.results import Boxes

        dets = merge_vehicle_classes(np.asarray(dets, np.float32).reshape(-1, 6), self.class_ids)
        dets = dets[dets[:, 4] >= self.conf]
        tracks = self._tracker.update(Boxes(dets, (self.height, self.width)), None)
        boxes = []
        for x1, y1, x2, y2, track_id, score, _cls, _ in tracks:
            bbox = (float(min(max(x1, 0.0), self.width)), float(min(max(y1, 0.0), self.height)),
                    float(min(max(x2, 0.0), self.width)), float(min(max(y2, 0.0), self.height)))
            boxes.append(TrackedBox(int(track_id), "vehicle", float(score), bbox))
        return TrackedFrame(frame, tuple(self._dedupe.update(frame, boxes)))


def track_all(frames: Iterable[tuple[int, np.ndarray]], frame_size: tuple[int, int], class_ids: Sequence[int],
              conf: float) -> list[TrackedFrame]:
    tracker = GateTracker(frame_size, class_ids, conf)
    return [tracker.update(frame, dets) for frame, dets in frames]


STATIC_TRAVEL_PX = 20.0  # diagnostics-only threshold for scenes without ``parked_max_travel_px``
EDGE_MARGIN_PX = 3.0  # a box this close to the frame border is clipped: its centre is not the vehicle's centre


def track_travel(tracked: Sequence[TrackedFrame], counting_point: str,
                 frame_size: tuple[int, int] | None = None, edge_margin: float = EDGE_MARGIN_PX) -> dict[int, float]:
    """Per track: maximum displacement (pixels) of its counting point from its first observed position.

    Not the cumulative path length, which grows with every frame of box jitter even for a parked car.
    With ``frame_size``, boxes within ``edge_margin`` of the frame border are skipped: a vehicle rolling into
    the frame and stopping in a queue at the edge has a clipped box whose centre barely moves (youtube2: queued
    cars at the north/south edges measured 13-25 px). Tracks with no fully visible box are left out: their
    travel is unknown, so they are never parked.
    """
    first: dict[int, Point] = {}
    travel: dict[int, float] = {}
    for tf in tracked:
        for box in tf.boxes:
            if frame_size is not None:
                x1, y1, x2, y2 = box.bbox
                if (x1 < edge_margin or y1 < edge_margin or x2 > frame_size[0] - edge_margin
                        or y2 > frame_size[1] - edge_margin):
                    continue
            point = box.point(counting_point)
            x0, y0 = first.setdefault(box.track_id, point)
            d = float(np.hypot(point[0] - x0, point[1] - y0))
            travel[box.track_id] = max(travel.get(box.track_id, 0.0), d)
    return travel


def parked_track_ids(travel: dict[int, float], max_travel_px: float | None) -> set[int]:
    """Tracks whose whole-clip travel is at most ``max_travel_px`` (none when the rule is off).

    Whole clip, not a sliding window: a car waiting at a red light drives in or out within the clip, so its
    travel is large; a car that pulls out of a parking spot is not parked at all, so every gate it crosses
    after it starts moving counts normally.
    """
    if max_travel_px is None:
        return set()
    return {tid for tid, d in travel.items() if d <= max_travel_px}


def without_tracks(tracked: Sequence[TrackedFrame], drop: set[int]) -> list[TrackedFrame]:
    if not drop:
        return list(tracked)
    return [TrackedFrame(tf.frame, tuple(b for b in tf.boxes if b.track_id not in drop)) for tf in tracked]


def parked_details(tracked: Sequence[TrackedFrame], parked: set[int], travel: dict[int, float], scene: SceneConfig,
                   fps: float) -> list[dict[str, Any]]:
    """Per parked track: lifetime, travel, median counting point, and the region / gates that point lies in."""
    seen: dict[int, list[tuple[int, float, float]]] = {}
    for tf in tracked:
        for tp in tf.points(scene.counting_point):
            if tp.track_id in parked:
                seen.setdefault(tp.track_id, []).append((tf.frame, *tp.point))
    out = []
    for tid in sorted(seen):
        obs = seen[tid]
        x, y = float(np.median([o[1] for o in obs])), float(np.median([o[2] for o in obs]))
        out.append({
            "track_id": tid, "first_s": round(obs[0][0] / fps, 2), "last_s": round(obs[-1][0] / fps, 2),
            "frames": len(obs), "travel_px": round(travel[tid], 1), "x": round(x, 1), "y": round(y, 1),
            "region": scene.locate((x, y)),
            "gates": [g for g, poly in scene.gates.items() if point_in_polygon((x, y), poly)],
        })
    return out


def process_scene(scene: SceneConfig, frames: Sequence[tuple[int, np.ndarray]], *, class_ids: Sequence[int],
                  conf: float, fps: float, model_id: str) -> tuple[list[TrackedFrame], GateRun, dict[str, Any]]:
    """Track cached detections and run the gate engine. Returns tracks, run, and diagnostics for the run log.

    The returned tracks include parked ones (for rendering); the run never sees them.
    """
    tracked = track_all(frames, tuple(scene.frame_size), class_ids, conf)
    travel = track_travel(tracked, scene.counting_point, tuple(scene.frame_size))
    parked = parked_track_ids(travel, scene.parked_max_travel_px)
    counted = without_tracks(tracked, parked)
    points = [(tf.frame, tf.points(scene.counting_point)) for tf in counted]
    run = run_gates(scene, points, fps=fps, frame_count=len(frames), model_id=model_id)
    static_px = scene.parked_max_travel_px or STATIC_TRAVEL_PX
    initial_ids = {tid for ids in run.initial.approach_tracks.values() for tid in ids}
    initial_ids |= set(run.initial.junction_tracks or ())
    diagnostics = {
        "track_ids": len({b.track_id for tf in tracked for b in tf.boxes}),
        "tracks_without_full_box": len({b.track_id for tf in tracked for b in tf.boxes} - set(travel)),
        "static_travel_px": static_px,
        "static_tracks": sorted(tid for tid, d in travel.items() if d <= static_px),
        "static_initial_tracks": sorted(tid for tid in initial_ids if travel.get(tid, 0.0) <= static_px),
        "parked_max_travel_px": scene.parked_max_travel_px,
        "parked_tracks": len(parked),
        "parked_track_ids": sorted(parked),
        "parked": parked_details(tracked, parked, travel, scene, fps),
        "travel_px_of_event_tracks": {str(tid): None if tid not in travel else round(travel[tid], 1)
                                      for tid in sorted({e["track_id"] for e in run.events})},
    }
    return tracked, run, diagnostics


# --- outputs ----------------------------------------------------------------------


def write_jsonl(path: Path, lines: Sequence[dict[str, Any]], model: type[GateEvent] | type[GateCounts]) -> None:
    """Validate every line against its contract model, then write atomically."""
    from .pipeline import ensure_outside_repo

    path = ensure_outside_repo(path)
    for line in lines:
        model.model_validate(line)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, separators=(",", ":")) + "\n")
    tmp.replace(path)


def run_summary(run: GateRun, scene: SceneConfig, meta: dict[str, Any]) -> dict[str, Any]:
    exits = [e for e in run.events if e["event"] == "intersection_exited"]
    entered_via = {t.track_id: t.gate_id for t in run.triggers if t.suppressed is None and t.gate_id.endswith("in.stop")}
    null_exits = sum(e["origin_arm"] is None for e in exits)
    return {
        **meta,
        "scene_id": scene.scene_id,
        "counting_point": scene.counting_point,
        "gate_rule": {"min_inside": scene.gate_min_inside, "window_frames": scene.gate_window_frames},
        "initial": {
            "window_frames": run.initial.window_frames,
            "min_observations": run.initial.min_observations,
            "vehicles_on_approach": run.initial.approach_counts(),
            "in_intersection": None if run.initial.junction_tracks is None else len(run.initial.junction_tracks),
            "approach_track_ids": {a: list(ids) for a, ids in run.initial.approach_tracks.items()},
            "junction_track_ids": None if run.initial.junction_tracks is None else list(run.initial.junction_tracks),
        },
        "triggers_by_gate": run.triggers_by_gate(),
        "suppressed_triggers": [
            {"track_id": t.track_id, "gate_id": t.gate_id, "frame": t.frame, "reason": t.suppressed,
             "x": None if t.point is None else round(t.point[0], 1),
             "y": None if t.point is None else round(t.point[1], 1),
             **({"entered_via": entered_via.get(t.track_id)} if t.suppressed == "already_entered" else {})}
            for t in run.triggers if t.suppressed
        ],
        "already_entered_by_gate_pair": dict(sorted(Counter(
            f"{entered_via.get(t.track_id)} -> {t.gate_id}" for t in run.triggers
            if t.suppressed == "already_entered").items())),
        "events": len(run.events),
        "intersection_exited": len(exits),
        "origin_arm_null": null_exits,
        "origin_arm_null_share": round(null_exits / len(exits), 4) if exits else None,
        "origin_arm_null_reasons": dict(run.origin_null),
        "clamps": [
            {"frame": c.frame, "t_s": c.t_s, "quantity": c.quantity, "arm": c.arm, "raw": c.raw,
             "track_id": c.track_id, "gate_id": c.gate_id}
            for c in run.clamps
        ],
        "warnings": scene.warnings(),
    }


def write_run_outputs(out_dir: Path, run: GateRun, scene: SceneConfig, meta: dict[str, Any]) -> dict[str, Any]:
    """``events.jsonl``, ``counts.jsonl``, and ``gate_run.json`` (initial state, clamps, diagnostics)."""
    from .pipeline import ensure_outside_repo

    out_dir = ensure_outside_repo(out_dir)
    write_jsonl(out_dir / "events.jsonl", run.events, GateEvent)
    write_jsonl(out_dir / "counts.jsonl", run.counts, GateCounts)
    summary = run_summary(run, scene, meta)
    tmp = out_dir / "gate_run.json.tmp"
    tmp.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    tmp.replace(out_dir / "gate_run.json")
    return summary


def write_sample(out_dir: Path, run: GateRun, seconds: float) -> tuple[int, int]:
    """First ``seconds`` of a run (events with ``t_s <= seconds``, counts lines ``t_s <= seconds``), for sharing.

    Consistent with each other: a counts line at ``t_s`` reflects exactly the triggers with ``frame / fps <= t_s``.
    """
    events = [e for e in run.events if e["t_s"] <= seconds]
    counts = [c for c in run.counts if c["t_s"] <= seconds]
    write_jsonl(out_dir / "events.jsonl", events, GateEvent)
    write_jsonl(out_dir / "counts.jsonl", counts, GateCounts)
    return len(events), len(counts)
