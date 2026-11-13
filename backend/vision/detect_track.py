"""YOLO11 detection + ByteTrack tracking via Ultralytics.

Weights are always loaded from an explicit path under ``UNIHACK_DIR/weights``
(downloaded there on first use), never from the working directory. Ultralytics
settings are isolated in ``UNIHACK_DIR/ultralytics_config`` because its default
settings point weights/runs/datasets at the enclosing git repository; analytics
sync and runtime auto-install are disabled.

Detection and tracking are split so detections can be cached per clip and
reused across confidence thresholds and line edits:

* YOLO runs once per frame at a score floor of ``min(conf, 0.25)``;
* detections below ``conf`` are dropped, then the rest go to Ultralytics'
  ``BYTETracker`` with its stock ``bytetrack.yaml`` settings, exactly as
  ``model.track`` would (NMS only suppresses lower-scored boxes, so filtering
  floor-level detections equals detecting at ``conf``).

``conf`` is therefore the detector score threshold: detections below it never
reach ByteTrack (Ultralytics' own tracking default is 0.1).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import numpy as np

from .counting import VEHICLE_CLASSES, TrackedBox
from .paths import VisionPaths

TRACKER_CONFIG = "bytetrack.yaml"
DETECTION_FLOOR = 0.25
SUPPORTED_MODELS = ("yolo11n.pt", "yolo11s.pt", "yolo11m.pt", "yolo11l.pt", "yolo11x.pt")


def configure_ultralytics(paths: VisionPaths) -> None:
    """Must run before ``ultralytics`` is first imported."""
    paths.ultralytics_config_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(paths.ultralytics_config_dir))
    os.environ.setdefault("YOLO_AUTOINSTALL", "False")
    os.environ.setdefault("YOLO_VERBOSE", "False")
    from ultralytics import settings

    settings.update(
        {
            "sync": False,
            "weights_dir": str(paths.weights_dir),
            "runs_dir": str(paths.output_dir / "ultralytics_runs"),
            "datasets_dir": str(paths.unihack_dir / "datasets"),
        }
    )


def ensure_weights(paths: VisionPaths, model_name: str) -> Path:
    if Path(model_name).name != model_name or not model_name.endswith(".pt"):
        raise ValueError(f"model must be a bare weights file name like yolo11m.pt, got {model_name!r}")
    configure_ultralytics(paths)
    target = paths.weights_dir / model_name
    if not target.exists():
        from ultralytics.utils.downloads import attempt_download_asset

        paths.weights_dir.mkdir(parents=True, exist_ok=True)
        attempt_download_asset(target)
    if not target.exists():
        raise FileNotFoundError(f"could not obtain weights {target}")
    return target


class DetectionCache:
    """Per-clip detections (``x1, y1, x2, y2, score, cls`` per row) as ``.npz``."""

    def __init__(self, root: Path | None) -> None:
        self.root = root
        self.last_detect_s: float | None = None  # detection time recorded with the last loaded entry

    def _path(self, clip_key: str) -> Path | None:
        return None if self.root is None else self.root / f"{clip_key}.npz"

    def load(self, clip_key: str, size: int) -> dict[int, np.ndarray] | None:
        path = self._path(clip_key)
        if path is None or not path.exists():
            return None
        with np.load(path) as data:
            if int(data["size"]) != size:
                return None
            frames, offsets, dets = data["frames"], data["offsets"], data["dets"]
            # Entries written before timing was recorded reuse their detections; runtime is unknown.
            self.last_detect_s = float(data["detect_s"]) if "detect_s" in data.files else None
        return {int(f): dets[offsets[i] : offsets[i + 1]] for i, f in enumerate(frames)}

    def save(self, clip_key: str, size: int, detections: dict[int, np.ndarray], detect_s: float) -> None:
        path = self._path(clip_key)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        frames = sorted(detections)
        offsets = np.cumsum([0] + [len(detections[f]) for f in frames])
        dets = np.concatenate([detections[f] for f in frames]) if frames else np.zeros((0, 6), np.float32)
        tmp = path.with_name(path.name + ".tmp.npz")
        np.savez_compressed(
            tmp, size=size, frames=np.array(frames, np.int32), offsets=offsets, dets=dets, detect_s=detect_s
        )
        tmp.replace(path)


class VehicleTracker:
    """Per-frame vehicle tracks. Call :meth:`begin_clip` before each clip."""

    def __init__(
        self,
        paths: VisionPaths,
        model_name: str = "yolo11m.pt",
        conf: float = 0.25,
        imgsz: int = 640,
        device: str = "cpu",
        use_cache: bool = True,
    ) -> None:
        if not 0.0 < conf < 1.0:
            raise ValueError("conf must be in (0, 1)")
        weights = ensure_weights(paths, model_name)
        from ultralytics import YOLO
        from ultralytics.utils import YAML, IterableSimpleNamespace
        from ultralytics.utils.checks import check_yaml

        self.model_name = model_name
        self.conf = conf
        self.imgsz = imgsz
        self.device = device
        self.floor = min(conf, DETECTION_FLOOR)
        self.model: Any = YOLO(str(weights), task="detect")
        names: dict[int, str] = self.model.names
        self.class_ids = sorted(i for i, n in names.items() if n in VEHICLE_CLASSES)
        missing = set(VEHICLE_CLASSES) - {names[i] for i in self.class_ids}
        if missing:
            raise ValueError(f"model {model_name} lacks vehicle classes {sorted(missing)}")
        self.names = names
        self._tracker_cfg = IterableSimpleNamespace(**YAML.load(check_yaml(TRACKER_CONFIG)))
        cache_root = None
        if use_cache:
            cache_root = paths.output_dir / "cache" / "detections" / f"{Path(model_name).stem}_imgsz{imgsz}_floor{self.floor:.2f}"
        self.cache = DetectionCache(cache_root)
        self._tracker: Any = None
        self._clip: tuple[str, int] | None = None
        self._cached: dict[int, np.ndarray] | None = None
        self._fresh: dict[int, np.ndarray] = {}
        self._fresh_s = 0.0
        self._cached_s: float | None = None
        # After end_clip(): YOLO time for the clip (measured now, or recorded when first cached).
        self.last_clip_detect_s: float | None = None
        self.last_clip_fresh_detect_s = 0.0  # YOLO time actually spent during the last clip

    @property
    def model_id(self) -> str:
        return f"{self.model_name}+bytetrack"

    def begin_clip(self, clip_key: str | None = None, size: int = 0) -> None:
        """Fresh tracker (IDs restart at 1) and the clip's cached detections, if any."""
        from ultralytics.trackers.byte_tracker import BYTETracker

        self._tracker = BYTETracker(args=self._tracker_cfg)  # track_buffer 30 frames = 1.2 s at 25 fps
        self._clip = (clip_key, size) if clip_key else None
        self._cached = self.cache.load(clip_key, size) if clip_key else None
        self._cached_s = self.cache.last_detect_s if self._cached is not None else None
        self._fresh, self._fresh_s = {}, 0.0

    def end_clip(self) -> None:
        if self._clip and self._cached is None and self._fresh:
            self.cache.save(self._clip[0], self._clip[1], self._fresh, self._fresh_s)
        if self._cached is None:
            self.last_clip_detect_s = self._fresh_s
        else:
            self.last_clip_detect_s = None if self._cached_s is None else self._cached_s + self._fresh_s
        self.last_clip_fresh_detect_s = self._fresh_s
        self._clip, self._cached, self._fresh = None, None, {}

    def reset(self) -> None:  # kept for callers that do not use the cache
        self.begin_clip()

    def detect(self, frame: Any) -> np.ndarray:
        result = self.model.predict(
            frame, conf=self.floor, classes=self.class_ids, imgsz=self.imgsz, device=self.device, verbose=False
        )[0]
        return result.boxes.data.cpu().numpy().astype(np.float32).reshape(-1, 6)

    def track(self, frame: Any, frame_index: int | None = None) -> list[TrackedBox]:
        from ultralytics.engine.results import Boxes

        if self._tracker is None:
            self.begin_clip()
        dets = None
        if self._cached is not None and frame_index is not None:
            dets = self._cached.get(frame_index)
        if dets is None:
            started = time.perf_counter()
            dets = self.detect(frame)
            self._fresh_s += time.perf_counter() - started
            if frame_index is not None:
                self._fresh[frame_index] = dets
        dets = dets[dets[:, 4] >= self.conf]
        boxes = Boxes(dets, frame.shape[:2])
        tracks = self._tracker.update(boxes, frame)
        height, width = frame.shape[:2]
        out = []
        for x1, y1, x2, y2, track_id, score, cls, _ in tracks:
            # Clip Kalman-extrapolated boxes to the image, as Ultralytics' Results.update does.
            bbox = (
                float(min(max(x1, 0.0), width)), float(min(max(y1, 0.0), height)),
                float(min(max(x2, 0.0), width)), float(min(max(y2, 0.0), height)),
            )
            out.append(TrackedBox(int(track_id), self.names[int(cls)], float(score), bbox))
        return out
