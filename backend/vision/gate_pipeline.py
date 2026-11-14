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
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from backend.models.gates import GateCounts, GateEvent

from .counting import TrackedBox
from .detections import merge_vehicle_classes
from .gates import GateRun, TrackPoint
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
    null_exits = sum(e["origin_arm"] is None for e in exits)
    return {
        **meta,
        "scene_id": scene.scene_id,
        "counting_point": scene.counting_point,
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
            {"track_id": t.track_id, "gate_id": t.gate_id, "frame": t.frame, "reason": t.suppressed}
            for t in run.triggers if t.suppressed
        ],
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
