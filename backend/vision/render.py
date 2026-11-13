"""Annotated demo video: boxes, class, track ID, approach lines/arrows, live counters."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .clips import Clip, format_utc
from .counting import CrossingEvent, LineCrossingCounter, TrackedBox
from .draw_lines import draw_approaches
from .pipeline import CameraContext, ClipResult, ensure_outside_repo, process_clip

CLASS_COLOURS = {
    "car": (255, 200, 0),
    "bus": (0, 0, 255),
    "truck": (0, 140, 255),
    "motorcycle": (255, 0, 255),
    "bicycle": (0, 255, 0),
}
BAR = 52
FLASH_FRAMES = 12


def _text(img: Any, text: str, org: tuple[int, int], scale: float = 0.55, colour=(255, 255, 255), thick: int = 1) -> None:
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, colour, thick, cv2.LINE_AA)


class DemoWriter:
    def __init__(self, out: Path, width: int, height: int, fps: float) -> None:
        self.path = ensure_outside_repo(out)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.size = (width, height + 2 * BAR)
        self.writer = None
        previous = cv2.utils.logging.getLogLevel()
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
        try:
            # H.264 when this OpenCV build has an encoder (pip wheels usually do not), else MPEG-4 Part 2.
            for fourcc in ("avc1", "mp4v"):
                writer = cv2.VideoWriter(str(self.path), cv2.VideoWriter_fourcc(*fourcc), fps, self.size)
                if writer.isOpened():
                    self.writer, self.fourcc = writer, fourcc
                    break
        finally:
            cv2.utils.logging.setLogLevel(previous)
        if self.writer is None:
            raise OSError(f"cannot open a video writer for {self.path}")

    def write(self, image: np.ndarray) -> None:
        assert image.shape[1::-1] == self.size, (image.shape, self.size)
        self.writer.write(image)

    def close(self) -> None:
        self.writer.release()


def compose(
    frame: np.ndarray,
    *,
    scale: int,
    context: CameraContext,
    clip: Clip,
    frame_index: int,
    frame_count: int,
    boxes: list[TrackedBox],
    counter: LineCrossingCounter | None,
    flashes: dict[str, int],
    model_label: str,
) -> np.ndarray:
    camera = context.camera
    view = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    totals = counter.live_totals() if counter else {a: 0 for a in camera.approach_ids}
    draw_approaches(view, camera.approaches, scale, counts=totals)
    for approach in camera.approaches:
        if flashes.get(approach.approach_id, 0) > 0:
            (x1, y1), (x2, y2) = approach.line
            cv2.line(view, (int(x1 * scale), int(y1 * scale)), (int(x2 * scale), int(y2 * scale)),
                     (255, 255, 255), 3 * scale, cv2.LINE_AA)
    for box in boxes:
        colour = CLASS_COLOURS.get(box.class_name, (200, 200, 200))
        x1, y1, x2, y2 = (int(v * scale) for v in box.bbox)
        counted = counter is not None and counter.is_counted(box.track_id)
        cv2.rectangle(view, (x1, y1), (x2, y2), colour, 3 if counted else 2, cv2.LINE_AA)
        cx, cy = (int(v * scale) for v in box.contact_point)
        cv2.circle(view, (cx, cy), 4, (255, 255, 255), -1, cv2.LINE_AA)
        label = f"#{box.track_id} {box.class_name} {box.confidence:.2f}" + (" +" if counted else "")
        _text(view, label, (x1, max(y1 - 5, 14)), 0.45, colour)
    width = view.shape[1]
    top = np.zeros((BAR, width, 3), np.uint8)
    bottom = np.zeros((BAR, width, 3), np.uint8)
    _text(top, f"{camera.intersection_id}  {camera.camera_id}   clip {clip.name}   "
               f"window end {format_utc(clip.observed_at_utc)} (approx.)", (8, 20), 0.5)
    _text(top, f"frame {frame_index + 1}/{frame_count}   {model_label}   "
               "counting: bottom-centre crosses line in arrow direction", (8, 42), 0.45, (200, 200, 200))
    if counter is not None:
        result = counter.result()
        parts = []
        for approach_id, by_class in result.counts_by_approach.items():
            detail = " ".join(f"{k}:{v}" for k, v in by_class.items() if k != "total" and v)
            parts.append(f"{approach_id} = {by_class['total']}" + (f" ({detail})" if detail else ""))
        _text(bottom, "   |   ".join(parts) or "no approaches", (8, 22), 0.5, (0, 255, 255))
    legend_x = 8
    for name, colour in CLASS_COLOURS.items():
        _text(bottom, name, (legend_x, 44), 0.42, colour)
        legend_x += 14 + cv2.getTextSize(name, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)[0][0]
    return np.vstack([top, view, bottom])


def title_card(size: tuple[int, int], lines: Sequence[str]) -> np.ndarray:
    width, height = size
    card = np.zeros((height, width, 3), np.uint8)
    for i, line in enumerate(lines):
        _text(card, line, (24, 60 + 34 * i), 0.7, (255, 255, 255) if i == 0 else (0, 220, 255), 1)
    return card


def render_demo(
    context: CameraContext,
    clips: Sequence[Clip],
    tracker: Any,
    out: Path,
    scale: int = 3,
    fps: float = 25.0,
) -> list[ClipResult]:
    width, height = (v * scale for v in context.camera.frame_size)
    writer = DemoWriter(out, width, height, fps)
    model_label = f"{tracker.model_id} conf>={tracker.conf}"
    results: list[ClipResult] = []
    try:
        for clip in clips:
            decision = context.decision(clip)
            if not decision.usable:
                card = title_card(writer.size, [f"{clip.name} skipped", f"reason: {decision.reason}", decision.evidence])
                for _ in range(int(fps * 1.5)):
                    writer.write(card)
                results.append(process_clip(clip, decision, context.camera, tracker))
                continue
            flashes: dict[str, int] = {}
            frame_count = decision.scan.frame_count if decision.scan else 0

            def on_frame(index: int, frame: np.ndarray, boxes: list[TrackedBox],
                         counter: LineCrossingCounter, events: list[CrossingEvent]) -> None:
                for key in list(flashes):
                    flashes[key] -= 1
                for event in events:
                    flashes[event.approach_id] = FLASH_FRAMES
                writer.write(compose(
                    frame, scale=scale, context=context, clip=clip, frame_index=index,
                    frame_count=frame_count, boxes=boxes, counter=counter, flashes=flashes,
                    model_label=model_label,
                ))

            result = process_clip(clip, decision, context.camera, tracker, on_frame)
            results.append(result)
            if result.status == "ok" and result.counts:
                summary = [f"{clip.name} result ({format_utc(clip.observed_at_utc)})"]
                for approach_id, by_class in result.counts.counts_by_approach.items():
                    summary.append(f"{approach_id}: {by_class['total']}  " +
                                   " ".join(f"{k}={v}" for k, v in by_class.items() if k != "total"))
                conf = result.counts.confidence
                summary.append(f"confidence: {'null' if conf is None else f'{conf:.2f}'}")
                card = title_card(writer.size, summary)
                for _ in range(int(fps * 1.2)):
                    writer.write(card)
    finally:
        writer.close()
    return results
