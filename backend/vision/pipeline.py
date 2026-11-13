"""Replay pipeline: view check -> YOLO11 + ByteTrack -> line crossings -> contract A.

Window semantics per clip (documented in ``README.md``):

* ``observed_at`` = filename download time converted to UTC (window end, approx.;
  TfL publishes 0-5 min earlier).
* ``window_duration_s`` = analysed duration: all decoded frames after the
  trimmed leading corrupt run, divided by fps. Equals the clip duration when
  nothing is trimmed (most clips).
* ``confidence`` = mean over counted tracks of each track's mean detection
  confidence; ``null`` when nothing was counted.
"""

from __future__ import annotations

import csv
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .clips import Clip, discover_clips, format_utc, probe, read_frames
from .config import CameraConfig
from .counting import CountResult, CrossingEvent, LineCrossingCounter, TrackedBox
from .observation import build_observation, counting_lines, observation_json
from .paths import REPO_ROOT, VisionPaths
from .view_check import ScanCache, ViewCheckConfig, ViewDecision, ViewIndex, build_view_index

FrameHook = Callable[[int, np.ndarray, list[TrackedBox], LineCrossingCounter, list[CrossingEvent]], None]


def ensure_outside_repo(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise ValueError(f"refusing to write generated output inside the repository: {resolved}")
    return resolved


def select_evenly(items: Sequence[Any], limit: int | None) -> list[Any]:
    """Deterministic, evenly spaced sample in time order (all items when no limit)."""
    if limit is None or limit >= len(items):
        return list(items)
    if limit <= 0:
        return []
    picks = sorted({int(round(i)) for i in np.linspace(0, len(items) - 1, limit)})
    return [items[i] for i in picks]


@dataclass
class CameraContext:
    camera: CameraConfig
    clips: list[Clip]
    index: ViewIndex

    @classmethod
    def build(
        cls,
        camera: CameraConfig,
        paths: VisionPaths,
        view_cfg: ViewCheckConfig = ViewCheckConfig(),
        progress: Callable[[str], None] | None = None,
    ) -> CameraContext:
        clips = discover_clips(paths.clips_dir, camera.camera_id)
        reference = None
        if camera.reference_frame:
            ref_path = paths.resolve(camera.reference_frame)
            reference = cv2.imread(str(ref_path))
            if reference is None and progress:
                progress(f"WARNING: reference frame {ref_path} not readable; every clip will be skipped")
        if reference is not None and tuple(reference.shape[1::-1]) != tuple(camera.frame_size):
            raise ValueError(f"{camera.camera_id}: reference frame size differs from configured frame_size")
        cache = ScanCache(paths.output_dir / "cache" / "view_scans", camera.camera_id, view_cfg)
        index = build_view_index(
            clips, reference, cache, read_frames, lambda p: probe(p).fps, view_cfg, progress
        )
        return cls(camera, clips, index)

    def decision(self, clip: Clip) -> ViewDecision:
        return self.index[clip.key]

    def usable_clips(self) -> list[Clip]:
        return [c for c in self.clips if self.index[c.key].usable]


@dataclass
class ClipResult:
    clip: Clip
    decision: ViewDecision
    status: str  # ok | skipped | error
    reason: str | None
    detail: str
    counts: CountResult | None = None
    observation: dict[str, Any] | None = None
    frames_total: int = 0
    window_duration_s: float | None = None
    runtime_s: float = 0.0  # wall time of this call (cache hits make it small)
    detect_s: float | None = None  # YOLO time for the clip, measured or recorded in the cache
    fresh_detect_s: float = 0.0  # YOLO time actually spent in this call

    @property
    def pipeline_runtime_s(self) -> float | None:
        """Full-cost estimate: tracking/counting wall time + YOLO time (cached or not)."""
        if self.detect_s is None:
            return None
        return self.runtime_s - self.fresh_detect_s + self.detect_s


def process_clip(
    clip: Clip,
    decision: ViewDecision,
    camera: CameraConfig,
    tracker: Any,
    on_frame: FrameHook | None = None,
) -> ClipResult:
    """Track and count one usable clip; returns a skipped result otherwise."""
    started = time.perf_counter()
    if not decision.usable:
        return ClipResult(clip, decision, "skipped", decision.reason, decision.evidence,
                          runtime_s=time.perf_counter() - started)
    scan = decision.scan
    assert scan is not None
    try:
        frames = read_frames(clip.path)
        info = probe(clip.path)
        if len(frames) != scan.frame_count:
            raise ValueError(f"decoded {len(frames)} frames, scan saw {scan.frame_count}")
        if tuple(frames[0].shape[1::-1]) != tuple(camera.frame_size):
            raise ValueError(f"frame size {frames[0].shape[1::-1]} != configured {camera.frame_size}")
        counter = LineCrossingCounter(counting_lines(camera))
        tracker.begin_clip(clip.key, clip.path.stat().st_size)
        corrupt = set(scan.corrupt_frames)
        try:
            for index in range(scan.start_frame, len(frames)):
                if index in corrupt:
                    continue
                boxes = tracker.track(frames[index], index)
                events = counter.update(index, boxes)
                if on_frame is not None:
                    on_frame(index, frames[index], boxes, counter, events)
        finally:
            tracker.end_clip()
        detect_s = getattr(tracker, "last_clip_detect_s", None)
        fresh_detect_s = getattr(tracker, "last_clip_fresh_detect_s", 0.0)
        counts = counter.result()
        window = (len(frames) - scan.start_frame) / info.fps
        observation = observation_json(
            build_observation(
                camera,
                observed_at_utc=clip.observed_at_utc,
                window_duration_s=window,
                counts=counts,
                model_id=tracker.model_id,
            )
        )
    except Exception as exc:  # noqa: BLE001 - one bad clip must not stop a replay
        return ClipResult(clip, decision, "error", "error", f"{type(exc).__name__}: {exc}",
                          runtime_s=time.perf_counter() - started)
    return ClipResult(
        clip, decision, "ok", None, decision.evidence, counts, observation,
        frames_total=len(frames), window_duration_s=window, runtime_s=time.perf_counter() - started,
        detect_s=detect_s, fresh_detect_s=fresh_detect_s,
    )


# --- outputs ----------------------------------------------------------------------

RUN_LOG_FIELDS = [
    "run_id", "run_started_utc", "intersection_id", "camera_id", "clip", "observed_at_utc",
    "status", "skip_reason", "detail", "model_id", "conf", "frames_total", "start_frame",
    "corrupt_frames", "window_duration_s", "counts_by_approach", "total", "confidence", "runtime_s",
]


def new_run_id() -> str:
    return datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")


def run_log_row(result: ClipResult, camera: CameraConfig, run_id: str, run_started: str,
                model_id: str, conf: float) -> dict[str, Any]:
    scan = result.decision.scan
    counts = result.counts.counts_by_approach if result.counts else None
    return {
        "run_id": run_id,
        "run_started_utc": run_started,
        "intersection_id": camera.intersection_id,
        "camera_id": camera.camera_id,
        "clip": result.clip.name,
        "observed_at_utc": format_utc(result.clip.observed_at_utc),
        "status": result.status,
        "skip_reason": result.reason or "",
        "detail": result.detail,
        "model_id": model_id,
        "conf": conf,
        "frames_total": scan.frame_count if scan else "",
        "start_frame": scan.start_frame if scan else "",
        "corrupt_frames": len(scan.corrupt_frames) if scan else "",
        "window_duration_s": f"{result.window_duration_s:.2f}" if result.window_duration_s else "",
        "counts_by_approach": json.dumps(counts, separators=(",", ":")) if counts else "",
        "total": sum(c["total"] for c in counts.values()) if counts else "",
        "confidence": "" if not result.counts or result.counts.confidence is None else f"{result.counts.confidence:.3f}",
        "runtime_s": f"{result.runtime_s:.2f}",
    }


def append_run_log(path: Path, rows: list[dict[str, Any]]) -> None:
    path = ensure_outside_repo(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            header = next(csv.reader(handle), None)
        if header != RUN_LOG_FIELDS:
            path.rename(path.with_name(f"{path.stem}.{datetime.now(UTC):%Y%m%dT%H%M%SZ}.old.csv"))
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUN_LOG_FIELDS)
        if new:
            writer.writeheader()
        writer.writerows(rows)


def write_observations(path: Path, observations: list[dict[str, Any]]) -> None:
    """Rewrite one intersection's JSONL with this run's observations (time order)."""
    path = ensure_outside_repo(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(observations, key=lambda o: (o["observed_at"], o["camera_id"]))
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for observation in ordered:
            handle.write(json.dumps(observation, separators=(",", ":")) + "\n")
    tmp.replace(path)
