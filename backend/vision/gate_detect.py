"""Gate mode detection: one YOLO pass over a scene's whole video, cached on disk.

The detector profile (``backend.vision.detections.PROFILES``) gives the weights,
input size, and vehicle classes. Its static-shape ONNX export is used when the
video letterboxes to exactly the export's input shape; otherwise, or when the
file or ``onnxruntime`` is missing, or the file's real input shape differs from
the profile, the ``.pt`` weights are used and the reason is logged and stored
with the cache (:func:`~backend.vision.detections.choose_backend`). Both give
the same boxes (20 s check on the top-down clip: zero unmatched detections).

Detections are stored at a score floor of ``DETECTION_FLOOR`` (below every
profile's ``conf``), restricted to the profile's vehicle classes, after
class-agnostic NMS, as ``x1, y1, x2, y2, score, cls`` rows in the model's own
class indices. Tracking, thresholds, and gates run later from the cache, so
editing gates or ``conf`` never re-runs YOLO.
"""

from __future__ import annotations

import importlib.util
import json
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from .detections import BackendChoice, DetectorProfile, choose_backend, vehicle_class_ids
from .paths import VisionPaths

DETECTION_FLOOR = 0.10  # = ByteTrack track_low_thresh; nothing below it is ever used
CACHE_VERSION = 1

Frames = list[tuple[int, np.ndarray]]


class GateDetector:
    """Per-frame vehicle detections for one video size."""

    def __init__(self, paths: VisionPaths, profile: DetectorProfile, frame_size: tuple[int, int],
                 log: Callable[[str], None] = print, floor: float = DETECTION_FLOOR) -> None:
        from .detect_track import configure_ultralytics

        configure_ultralytics(paths)
        from ultralytics import YOLO

        self.profile, self.floor = profile, floor
        onnx_path = paths.weights_dir / profile.onnx_weights if profile.onnx_weights else None
        choice = choose_backend(
            profile, frame_size,
            onnx_file_exists=bool(onnx_path and onnx_path.exists()),
            onnxruntime_available=importlib.util.find_spec("onnxruntime") is not None,
        )
        if choice.backend == "onnx":
            actual = _onnx_input_hw(paths.weights_dir / choice.weights)
            if actual != choice.imgsz:
                choice = BackendChoice("pt", profile.weights, profile.imgsz,
                                       f"{choice.weights} input is {actual}, profile says {choice.imgsz}; "
                                       f"using {profile.weights}")
        if choice.fallback_reason:
            log(f"detector fallback: {choice.fallback_reason}")
        weights = paths.weights_dir / choice.weights
        if not weights.exists():
            raise FileNotFoundError(paths.missing(f"weights for profile {profile.model_id}", weights))
        self.choice = choice
        self.model: Any = YOLO(str(weights), task="detect")
        self.names: dict[int, str] = dict(self.model.names)
        self.class_ids = vehicle_class_ids(self.names, profile.vehicle_classes)
        log(f"detector: {profile.model_id} via {choice.backend} ({choice.weights}), imgsz {choice.imgsz}, "
            f"floor {floor}, vehicle classes {[self.names[i] for i in self.class_ids]}")

    def detect(self, frame: np.ndarray) -> np.ndarray:
        result = self.model.predict(frame, imgsz=self.choice.imgsz, conf=self.floor, agnostic_nms=True,
                                    classes=self.class_ids, device="cpu", verbose=False)[0]
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return np.zeros((0, 6), np.float32)
        return np.concatenate([boxes.xyxy.cpu().numpy(), boxes.conf.cpu().numpy()[:, None],
                               boxes.cls.cpu().numpy()[:, None]], axis=1).astype(np.float32)


def _onnx_input_hw(path: Path) -> tuple[int, int] | None:
    import onnxruntime as ort

    shape = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"]).get_inputs()[0].shape
    return (shape[2], shape[3]) if len(shape) == 4 and all(isinstance(v, int) for v in shape[2:]) else None


def cache_path(paths: VisionPaths, profile: DetectorProfile, video: Path, floor: float = DETECTION_FLOOR) -> Path:
    return (paths.output_dir / "cache" / "gate_detections" / f"{profile.model_id}_imgsz{profile.imgsz}_floor{floor:.2f}"
            / f"{video.stem}.npz")


def _video_key(video: Path) -> dict[str, Any]:
    stat = video.stat()
    return {"video": str(video.resolve()), "video_bytes": stat.st_size}


def load_detections(path: Path, video: Path) -> tuple[Frames, dict[str, Any]] | None:
    """Cached frames and metadata, or ``None`` when absent or made from a different video file."""
    meta_path = path.with_suffix(".json")
    if not path.exists() or not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("cache_version") != CACHE_VERSION or any(meta.get(k) != v for k, v in _video_key(video).items()):
        return None
    with np.load(path) as data:
        frames, offsets, dets = data["frames"], data["offsets"], data["dets"]
    return [(int(f), dets[offsets[i]:offsets[i + 1]]) for i, f in enumerate(frames)], meta


def save_detections(path: Path, frames: Frames, meta: dict[str, Any]) -> None:
    from .pipeline import ensure_outside_repo

    path = ensure_outside_repo(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    offsets = np.cumsum([0] + [len(d) for _, d in frames])
    dets = np.concatenate([d for _, d in frames]) if frames else np.zeros((0, 6), np.float32)
    tmp = path.with_name(path.stem + ".tmp.npz")
    np.savez_compressed(tmp, frames=np.array([f for f, _ in frames], np.int32), offsets=offsets, dets=dets)
    tmp.replace(path)
    meta_tmp = path.with_suffix(".json.tmp")
    meta_tmp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    meta_tmp.replace(path.with_suffix(".json"))


def detect_video(paths: VisionPaths, profile: DetectorProfile, video: Path, *, use_cache: bool = True,
                 log: Callable[[str], None] = print, progress_every_s: float = 60.0) -> tuple[Frames, dict[str, Any]]:
    """Detections for every decoded frame of ``video`` (from the cache when valid)."""
    import cv2

    target = cache_path(paths, profile, video)
    if use_cache and (cached := load_detections(target, video)) is not None:
        log(f"detections from cache {target} ({cached[1]['frames']} frames, backend {cached[1]['backend']})")
        return cached
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise OSError(f"cannot open video {video}")
    try:
        frame_size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        header_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        detector = GateDetector(paths, profile, frame_size, log=log)
        frames: Frames = []
        detect_s, started, last_log = 0.0, time.monotonic(), time.monotonic()
        while True:
            ok, image = cap.read()
            if not ok:
                break
            t0 = time.perf_counter()
            frames.append((len(frames), detector.detect(image)))
            detect_s += time.perf_counter() - t0
            if time.monotonic() - last_log >= progress_every_s:
                last_log = time.monotonic()
                log(f"  frame {len(frames)}/{header_frames} ({1000 * detect_s / len(frames):.0f} ms/frame)")
    finally:
        cap.release()
    if not frames:
        raise OSError(f"no frames decoded from {video}")
    meta = {
        "cache_version": CACHE_VERSION, **_video_key(video),
        "model_id": profile.model_id, "backend": detector.choice.backend, "weights": detector.choice.weights,
        "imgsz": detector.choice.imgsz, "fallback_reason": detector.choice.fallback_reason,
        "floor": detector.floor, "class_ids": detector.class_ids,
        "class_names": [detector.names[i] for i in detector.class_ids],
        "frame_size": list(frame_size), "fps": fps, "frames": len(frames), "header_frames": header_frames,
        "detect_s": round(detect_s, 1), "ms_per_frame": round(1000 * detect_s / len(frames), 1),
        "wall_s": round(time.monotonic() - started, 1), "profile": asdict(profile),
    }
    save_detections(target, frames, meta)
    log(f"detections cached at {target}: {len(frames)} frames, {meta['ms_per_frame']} ms/frame ({meta['backend']})")
    return frames, meta


__all__ = ["DETECTION_FLOOR", "GateDetector", "cache_path", "detect_video", "load_detections", "save_detections"]
