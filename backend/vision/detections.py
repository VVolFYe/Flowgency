"""Detector profiles and detection post-processing (numpy only; no YOLO import).

Detections are ``float32`` arrays with one ``x1, y1, x2, y2, score, cls`` row
per box, in pixels of the original frame.

Root cause of the London double counts (detector side)
------------------------------------------------------
The detector flips one vehicle between two box extents with different labels,
e.g. a whole-vehicle ``truck`` box and a smaller ``car`` box over its front.
Ultralytics' NMS is per-class by default, so when both appear in one frame
neither is suppressed; even class-agnostic NMS at IoU 0.7 keeps them because a
box nested inside another has a low IoU (0.35-0.46 in the traced London case,
while 89-100 % of the small box lies inside the large one). ByteTrack does not
gate on class and starts a second track on the extra box, and the line counter
counts each track. :func:`agnostic_nms` therefore ignores labels and also
suppresses a lower-scored box when most of the smaller of the two lies inside
the other. The tracker-side half of the fix is
:class:`backend.vision.track_filter.DuplicateTrackFilter`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

import numpy as np

NMS_IOU = 0.7  # same IoU as Ultralytics' default NMS
NMS_CONTAIN = 0.85  # suppress when this share of the smaller box lies inside the higher-scored box
VEHICLE = "vehicle"
VEHICLE_CLASS_ID = 0

CountingPoint = Literal["bottom_center", "center"]
COUNTING_POINTS: tuple[str, ...] = ("bottom_center", "center")


@dataclass(frozen=True)
class DetectorProfile:
    """One weights file and how its classes map to the single ``vehicle`` class.

    ``conf`` is this model's detector score threshold. ``vehicle_classes`` are
    the model's own class names merged into ``vehicle`` before tracking; every
    other class (pedestrians, bicycles, ...) is dropped.
    """

    model_id: str
    weights: str
    vehicle_classes: tuple[str, ...]
    conf: float
    notes: str = ""
    imgsz: int = 640  # long side of the letterboxed model input
    # Optional faster static-shape ONNX export of the same weights and its input (height, width).
    # Used only when the clip letterboxes to exactly that shape; otherwise ``weights`` (.pt) is used.
    onnx_weights: str | None = None
    onnx_input_hw: tuple[int, int] | None = None


PROFILES: dict[str, DetectorProfile] = {
    profile.model_id: profile
    for profile in (
        DetectorProfile(
            model_id="yolo11s_coco",
            weights="yolo11s_coco.pt",
            vehicle_classes=("car", "truck", "bus", "motorcycle"),
            conf=0.25,
            notes="COCO-pretrained yolo11s; street-level views only (finds no vehicles top-down)",
        ),
        DetectorProfile(
            model_id="yolo11s_visdrone",
            weights="yolo11s_visdrone.pt",
            vehicle_classes=("car", "van", "truck", "bus", "motor"),
            # 0.15 lets ByteTrack's second stage (scores 0.10-0.25) keep existing tracks alive; new
            # tracks still need 0.25 (bytetrack.yaml new_track_thresh). 20 s check on the top-down
            # clip: same 62 track IDs as 0.25, track gaps 20 -> 15.
            conf=0.15,
            notes="yolo11s trained by the team on VisDrone (imgsz 640); top-down views. imgsz 960 keeps a "
            "shaded car under a signal pole that 640 loses. VisDrone data is CC BY-NC-SA 3.0 (non-commercial)",
            imgsz=960,
            onnx_weights="yolo11s_visdrone_544x960.onnx",  # 1.3x faster than .pt on the dev CPU, same boxes
            onnx_input_hw=(544, 960),  # a 16:9 frame letterboxed to long side 960
        ),
    )
}


def get_profile(model_id: str) -> DetectorProfile:
    try:
        return PROFILES[model_id]
    except KeyError:
        raise ValueError(f"unknown model_id {model_id!r}; known: {', '.join(sorted(PROFILES))}") from None


LETTERBOX_STRIDE = 32


def letterbox_shape(frame_size: tuple[int, int], imgsz: int, stride: int = LETTERBOX_STRIDE) -> tuple[int, int]:
    """Model input ``(height, width)`` for a ``(width, height)`` frame: long side ``imgsz``, sides padded up to
    a multiple of ``stride`` (what Ultralytics' rectangular letterbox feeds a ``.pt`` model)."""
    width, height = frame_size
    if width <= 0 or height <= 0 or imgsz <= 0:
        raise ValueError("frame size and imgsz must be positive")
    ratio = imgsz / max(width, height)
    new_h, new_w = round(height * ratio), round(width * ratio)
    return (-(-new_h // stride) * stride, -(-new_w // stride) * stride)


@dataclass(frozen=True)
class BackendChoice:
    backend: Literal["onnx", "pt"]
    weights: str  # file name under the weights directory
    imgsz: int | tuple[int, int]  # value passed to Ultralytics ``predict``
    fallback_reason: str | None = None  # why an available ONNX export was not used


def choose_backend(profile: DetectorProfile, frame_size: tuple[int, int], *, onnx_file_exists: bool,
                   onnxruntime_available: bool) -> BackendChoice:
    """The profile's ONNX export when the clip letterboxes to its exact input shape, else the ``.pt``.

    A static-shape export cannot take another input shape, and squeezing a different aspect ratio into
    it would change the detections, so any mismatch falls back to the ``.pt`` (with a reason to log).
    """
    pt = BackendChoice("pt", profile.weights, profile.imgsz)
    if profile.onnx_weights is None or profile.onnx_input_hw is None:
        return pt
    expected = letterbox_shape(frame_size, profile.imgsz)
    reason = None
    if expected != tuple(profile.onnx_input_hw):
        reason = (f"frame {frame_size[0]}x{frame_size[1]} letterboxes to {expected[0]}x{expected[1]} at imgsz "
                  f"{profile.imgsz}, but {profile.onnx_weights} takes {profile.onnx_input_hw[0]}x{profile.onnx_input_hw[1]}")
    elif not onnx_file_exists:
        reason = f"{profile.onnx_weights} not found"
    elif not onnxruntime_available:
        reason = "onnxruntime is not installed"
    if reason is not None:
        return BackendChoice("pt", profile.weights, profile.imgsz, f"{reason}; using {profile.weights}")
    return BackendChoice("onnx", profile.onnx_weights, tuple(profile.onnx_input_hw))


def vehicle_class_ids(names: Mapping[int, str], vehicle_classes: Iterable[str]) -> list[int]:
    """Model class indices to merge; every listed name must exist in the model."""
    wanted = tuple(vehicle_classes)
    ids = sorted(i for i, n in names.items() if n in wanted)
    missing = set(wanted) - {names[i] for i in ids}
    if missing:
        raise ValueError(f"model lacks vehicle classes {sorted(missing)}; it has {sorted(names.values())}")
    return ids


def box_iou(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    """IoU of one ``x1, y1, x2, y2`` box with each row of ``boxes``."""
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = (box[2] - box[0]) * (box[3] - box[1])
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    union = area + areas - inter
    return np.divide(inter, union, out=np.zeros_like(inter, dtype=np.float64), where=union > 0)


def box_ios(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    """Intersection over the *smaller* of the two areas (1.0 when one box contains the other)."""
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    smaller = np.minimum((box[2] - box[0]) * (box[3] - box[1]), (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]))
    return np.divide(inter, smaller, out=np.zeros_like(inter, dtype=np.float64), where=smaller > 0)


def agnostic_nms(dets: np.ndarray, iou: float = NMS_IOU, contain: float = NMS_CONTAIN) -> np.ndarray:
    """Greedy NMS ignoring class: keep the highest-scored box of each overlapping group.

    A lower-scored box is suppressed when its IoU with a kept box exceeds
    ``iou`` or when at least ``contain`` of the smaller box lies inside the
    other (nested duplicate). Output keeps input row order among kept boxes
    (deterministic; ties in score keep the earlier row). Suppression only ever
    removes lower-scored boxes, so filtering by score before or after gives
    the same result.
    """
    if len(dets) <= 1:
        return dets
    order = np.argsort(-dets[:, 4], kind="stable")
    suppressed = np.zeros(len(dets), bool)
    keep = []
    for rank, i in enumerate(order):
        if suppressed[i]:
            continue
        keep.append(i)
        rest = order[rank + 1 :]
        rest = rest[~suppressed[rest]]
        if len(rest):
            overlap = (box_iou(dets[i], dets[rest]) > iou) | (box_ios(dets[i], dets[rest]) >= contain)
            suppressed[rest[overlap]] = True
    return dets[np.sort(np.array(keep))]


def merge_vehicle_classes(dets: np.ndarray, class_ids: Iterable[int], iou: float = NMS_IOU) -> np.ndarray:
    """Drop non-vehicle rows, relabel the rest ``vehicle`` (class 0), then class-agnostic NMS."""
    ids = np.array(sorted(class_ids), dtype=dets.dtype if len(dets) else np.float32)
    kept = dets[np.isin(dets[:, 5], ids)].copy() if len(dets) else dets.reshape(-1, 6)
    kept[:, 5] = VEHICLE_CLASS_ID
    return agnostic_nms(kept, iou)


def counting_point(bbox: tuple[float, float, float, float], mode: str) -> tuple[float, float]:
    """``bottom_center`` (road contact, street-level views) or ``center`` (top-down views)."""
    x1, y1, x2, y2 = bbox
    if mode == "bottom_center":
        return ((x1 + x2) / 2.0, y2)
    if mode == "center":
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
    raise ValueError(f"counting point must be one of {COUNTING_POINTS}, got {mode!r}")
