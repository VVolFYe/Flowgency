"""Standalone evaluation of the emergency-vehicle crop classifier on one eye-level video (CPU only).

Vehicles are detected and tracked exactly as in line-counting mode (:class:`~backend.vision.detect_track.VehicleTracker`:
COCO vehicle classes, stock ByteTrack, class-agnostic NMS, duplicate-track filter). Every ``--every`` frames each
tracked box is cropped with 10 % padding per side (as in classifier training) and classified; an
:class:`EmergencyVoter` turns the per-crop probabilities into a sticky per-track flag. Not wired into the pipeline yet.

    python -m backend.vision.eval_emergency VIDEO [--cls emergency_cls.pt] [--det yolo11s_coco.pt] [--out PATH]
"""

from __future__ import annotations

import argparse
import time
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np

from .detections import get_profile
from .paths import VisionPaths
from .weights import fetch_weights

EMERGENCY_CLASS = "emergency"
STREET_PROFILE = get_profile("yolo11s_coco")  # the COCO detector used for street-level (eye-level) views
CROP_PAD = 0.10  # per side, as in training
MIN_CROP_SIDE = 32  # px
POSITIVE_P = 0.5  # a single prediction counts as an emergency vote at p >= this
GREY, RED, BLUE, WHITE = (160, 160, 160), (0, 0, 255), (255, 0, 0), (255, 255, 255)  # BGR
BLINK_S = 0.25  # flagged boxes alternate red/blue at this period of video time


class EmergencyVoter:
    """Sliding-window vote per track; once flagged, a track stays flagged."""

    def __init__(self, window: int = 10, min_votes: int = 5, thresh: float = 0.6) -> None:
        if not 1 <= min_votes <= window or not 0.0 < thresh <= 1.0:
            raise ValueError("need 1 <= min_votes <= window and 0 < thresh <= 1")
        self.window, self.min_votes, self.thresh = window, min_votes, thresh
        self.history: dict[int, deque[float]] = {}
        self.flagged_at: dict[int, float] = {}  # track_id -> time (s) first flagged

    def update(self, track_id: int, p_emergency: float, t_s: float) -> bool:
        votes = self.history.setdefault(track_id, deque(maxlen=self.window))
        votes.append(p_emergency)
        if (track_id not in self.flagged_at and len(votes) >= self.min_votes
                and self.positives(track_id) / len(votes) >= self.thresh):
            self.flagged_at[track_id] = t_s
        return track_id in self.flagged_at

    def positives(self, track_id: int) -> int:
        return sum(p >= POSITIVE_P for p in self.history.get(track_id, ()))

    def is_flagged(self, track_id: int) -> bool:
        return track_id in self.flagged_at


def load_classifier(path: Path) -> tuple[Any, int]:
    """The classifier and the index of its ``emergency`` class (looked up by name)."""
    from ultralytics import YOLO

    model = YOLO(str(path))
    names: dict[int, str] = model.names
    if model.task != "classify" or EMERGENCY_CLASS not in names.values():
        raise ValueError(f"{path} must be a classify model with an {EMERGENCY_CLASS!r} class; got {model.task} {names}")
    if len(names) < 2:  # softmax over one output is always 1.0
        raise ValueError(f"{path} has a single class {names}; p_emergency would be 1.0 for every crop")
    return model, next(i for i, n in names.items() if n == EMERGENCY_CLASS)


def pad_crop(frame: np.ndarray, bbox: tuple[float, float, float, float]) -> np.ndarray | None:
    """Box padded by ``CROP_PAD`` per side and clamped to the frame; ``None`` if its short side is too small."""
    x1, y1, x2, y2 = bbox
    px, py = CROP_PAD * (x2 - x1), CROP_PAD * (y2 - y1)
    h, w = frame.shape[:2]
    x1, y1 = max(0, int(x1 - px)), max(0, int(y1 - py))
    x2, y2 = min(w, int(round(x2 + px))), min(h, int(round(y2 + py)))
    crop = frame[y1:y2, x1:x2]
    return crop if min(crop.shape[:2]) >= MIN_CROP_SIDE else None


def draw_track(frame: np.ndarray, box: Any, flagged: bool, p: float | None, t_s: float) -> None:
    """Thin grey box for a normal track; flashing red/blue, filled and labelled ``EMERGENCY`` for a flagged one."""
    import cv2

    x1, y1, x2, y2 = map(int, box.bbox)
    font = cv2.FONT_HERSHEY_SIMPLEX
    if not flagged:
        label = str(box.track_id) if p is None else f"{box.track_id} p={p:.2f}"
        cv2.rectangle(frame, (x1, y1), (x2, y2), GREY, 1)
        cv2.putText(frame, label, (x1, max(12, y1 - 4)), font, 0.45, GREY, 1, cv2.LINE_AA)
        return
    color = RED if int(t_s / BLINK_S) % 2 == 0 else BLUE
    roi = frame[y1:y2, x1:x2]
    if roi.size:
        cv2.addWeighted(roi, 0.75, np.full_like(roi, color), 0.25, 0, dst=roi)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
    label = f"EMERGENCY {box.track_id}"
    (tw, th), base = cv2.getTextSize(label, font, 0.6, 2)
    top = y1 - th - base - 6 if y1 - th - base - 6 >= 0 else y1  # above the box, or inside it at the frame top
    cv2.rectangle(frame, (x1, top), (x1 + tw + 8, top + th + base + 6), color, -1)
    cv2.putText(frame, label, (x1 + 4, top + th + 3), font, 0.6, WHITE, 2, cv2.LINE_AA)


def main(argv: list[str] | None = None) -> int:
    paths = VisionPaths.from_env()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("video", type=Path)
    p.add_argument("--cls", default="emergency_cls.pt",
                   help="classifier weights: a file name under UNIHACK_DIR/weights (registered files are "
                   "downloaded when missing) or a path")
    p.add_argument("--det", default=STREET_PROFILE.weights, help="detector weights file name under UNIHACK_DIR/weights")
    p.add_argument("--every", type=int, default=3, help="classify every N frames")
    p.add_argument("--window", type=int, default=10)
    p.add_argument("--min-votes", type=int, default=5)
    p.add_argument("--thresh", type=float, default=0.6, help="share of positive votes needed to flag")
    p.add_argument("--out", type=Path, help="annotated mp4 (default: <video>_emergency.mp4 next to the input)")
    args = p.parse_args(argv)
    if args.every < 1:
        p.error("--every must be >= 1")
    voter = EmergencyVoter(args.window, args.min_votes, args.thresh)
    if not args.video.exists():
        raise FileNotFoundError(f"video not found: {args.video}")
    if Path(args.cls).name == args.cls:
        cls_path = fetch_weights(paths, args.cls, "classifier weights")
    elif not (cls_path := Path(args.cls)).exists():
        raise FileNotFoundError(f"classifier weights not found: {cls_path}")

    from .detect_track import VehicleTracker, configure_ultralytics
    from .pipeline import ensure_outside_repo

    configure_ultralytics(paths)  # before ultralytics is first imported
    import cv2

    classifier, emergency_idx = load_classifier(cls_path)
    tracker = VehicleTracker(paths, args.det, conf=STREET_PROFILE.conf, imgsz=STREET_PROFILE.imgsz, use_cache=False)
    tracker.begin_clip()

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise OSError(f"cannot open video {args.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0  # assumed when the header has no frame rate
    size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    out = ensure_outside_repo(args.out or args.video.with_name(f"{args.video.stem}_emergency.mp4"))
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if not writer.isOpened():
        raise OSError(f"cannot write {out}")

    seen: set[int] = set()
    latest_p: dict[int, float] = {}
    frame_index, started = 0, time.perf_counter()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            boxes = tracker.track(frame, frame_index)
            seen.update(b.track_id for b in boxes)
            if frame_index % args.every == 0:
                crops = [(b.track_id, c) for b in boxes if (c := pad_crop(frame, b.bbox)) is not None]
                if crops:
                    results = classifier.predict([c for _, c in crops], device="cpu", verbose=False)
                    for (track_id, _), result in zip(crops, results):
                        latest_p[track_id] = float(result.probs.data[emergency_idx])
                        voter.update(track_id, latest_p[track_id], frame_index / fps)
            for b in sorted(boxes, key=lambda b: voter.is_flagged(b.track_id)):  # flagged drawn on top
                draw_track(frame, b, voter.is_flagged(b.track_id), latest_p.get(b.track_id), frame_index / fps)
            writer.write(frame)
            frame_index += 1
    finally:
        cap.release()
        writer.release()

    elapsed = time.perf_counter() - started
    print(f"annotated video: {out}")
    print(f"total tracks: {len(seen)}")
    print(f"flagged tracks: {len(voter.flagged_at)}")
    for track_id, t_s in sorted(voter.flagged_at.items(), key=lambda kv: kv[1]):
        print(f"  id {track_id}: first flagged at {t_s:.2f} s")
    print(f"average fps: {frame_index / elapsed:.2f} ({frame_index} frames in {elapsed:.1f} s)" if frame_index else
          "no frames decoded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
