"""YOLO11 detection + ByteTrack tracking via Ultralytics.

Weights are always loaded from an explicit path under ``UNIHACK_DIR/weights``
(downloaded there on first use), never from the working directory. Ultralytics
settings are isolated in ``UNIHACK_DIR/ultralytics_config`` because its default
settings point weights/runs/datasets at the enclosing git repository; analytics
sync and runtime auto-install are disabled.

``conf`` is the detector score threshold passed to ``model.track``: detections
below it never reach ByteTrack (Ultralytics' own tracking default is 0.1).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .counting import VEHICLE_CLASSES, TrackedBox
from .paths import VisionPaths

TRACKER_CONFIG = "bytetrack.yaml"
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


class VehicleTracker:
    """Per-frame vehicle tracks; call :meth:`reset` between clips."""

    def __init__(
        self,
        paths: VisionPaths,
        model_name: str = "yolo11m.pt",
        conf: float = 0.25,
        imgsz: int = 640,
        device: str = "cpu",
    ) -> None:
        if not 0.0 < conf < 1.0:
            raise ValueError("conf must be in (0, 1)")
        weights = ensure_weights(paths, model_name)
        from ultralytics import YOLO

        self.model_name = model_name
        self.conf = conf
        self.imgsz = imgsz
        self.device = device
        self.model: Any = YOLO(str(weights), task="detect")
        names: dict[int, str] = self.model.names
        self.class_ids = sorted(i for i, n in names.items() if n in VEHICLE_CLASSES)
        missing = set(VEHICLE_CLASSES) - {names[i] for i in self.class_ids}
        if missing:
            raise ValueError(f"model {model_name} lacks vehicle classes {sorted(missing)}")
        self.names = names

    @property
    def model_id(self) -> str:
        return f"{self.model_name}+bytetrack"

    def reset(self) -> None:
        """Clear tracker state and restart track IDs (new clip)."""
        predictor = getattr(self.model, "predictor", None)
        for tracker in getattr(predictor, "trackers", None) or ():
            tracker.reset()

    def track(self, frame: Any) -> list[TrackedBox]:
        result = self.model.track(
            frame,
            persist=True,
            tracker=TRACKER_CONFIG,
            conf=self.conf,
            classes=self.class_ids,
            imgsz=self.imgsz,
            device=self.device,
            verbose=False,
        )[0]
        boxes = result.boxes
        if boxes is None or boxes.id is None:
            return []
        out = []
        for track_id, cls, score, xyxy in zip(
            boxes.id.int().tolist(),
            boxes.cls.int().tolist(),
            boxes.conf.tolist(),
            boxes.xyxy.tolist(),
        ):
            out.append(TrackedBox(int(track_id), self.names[int(cls)], float(score), tuple(xyxy)))
        return out
