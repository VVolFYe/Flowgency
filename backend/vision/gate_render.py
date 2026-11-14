"""Gate mode demo video: tracks, gates flashing on triggers, and the published counts.

The panel shows the ``counts.jsonl`` line consumers would read at that moment
(the last whole second ``t_s <= frame / fps``), so the demo shows exactly what
is published, including its up-to-1-s lag. Gates flash white for a few frames
when a track triggers them. Suppressed triggers flash too and are marked in the
event list: ``(init)`` for initial-state vehicles, ``SUPPRESSED (already
entered)`` for a second stop-gate trigger by a track that already entered. Box colour: the arm of the track's latest
event (grey after ``intersection_exited``); before any event, its arm if it was
counted on that approach at the start, white if it started in the junction,
else green.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

from .draw_gates import ARM_COLOURS, draw_gates
from .gate_pipeline import TrackedFrame
from .gates import GateRun, time_s
from .scene import ARMS, SceneConfig, gate_arm, gate_kind

FLASH_FRAMES = 8
EVENT_LINES = 6
NO_EVENT = (80, 255, 80)
EXITED = (170, 170, 170)


def render_gate_demo(video: Path, scene: SceneConfig, tracked: Sequence[TrackedFrame], run: GateRun, out: Path,
                     *, fps: float, scale: float = 2 / 3, start_frame: int = 0, end_frame: int | None = None,
                     log: Callable[[str], None] = print) -> Path:
    import cv2

    from .pipeline import ensure_outside_repo

    out = ensure_outside_repo(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    by_frame = {tf.frame: tf for tf in tracked}
    triggers_at: dict[int, list] = {}
    for t in run.triggers:
        triggers_at.setdefault(t.frame, []).append(t)
    end = len(tracked) if end_frame is None else min(end_frame, len(tracked))
    width, height = (round(v * scale) for v in scene.frame_size)
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    flash: dict[str, int] = {}
    colour: dict[int, tuple[int, int, int]] = {
        tid: ARM_COLOURS[arm] for arm, ids in run.initial.approach_tracks.items() for tid in ids}
    colour.update({tid: (255, 255, 255) for tid in run.initial.junction_tracks or ()})
    recent: list[str] = []
    # replay triggers before start_frame so colours and the event list are right when starting mid-clip
    for frame in range(0, start_frame):
        for t in triggers_at.get(frame, ()):
            _apply(t, colour, recent, fps)
    try:
        for frame in range(start_frame, end):
            ok, image = cap.read()
            if not ok:
                break
            image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
            for t in triggers_at.get(frame, ()):
                flash[t.gate_id] = FLASH_FRAMES
                _apply(t, colour, recent, fps)
            draw_gates(image, scene, scale, flashes=flash, labels=False)
            flash = {g: n - 1 for g, n in flash.items() if n > 1}
            tf = by_frame.get(frame)
            for box in tf.boxes if tf else ():
                c = colour.get(box.track_id, NO_EVENT)
                x1, y1, x2, y2 = (int(round(v * scale)) for v in box.bbox)
                cv2.rectangle(image, (x1, y1), (x2, y2), c, 2)
                cx, cy = box.point(scene.counting_point)
                cv2.circle(image, (int(cx * scale), int(cy * scale)), 3, c, -1)
                cv2.putText(image, str(box.track_id), (x1, max(y1 - 3, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                            (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(image, str(box.track_id), (x1, max(y1 - 3, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, c, 1,
                            cv2.LINE_AA)
            _panel(image, run, frame, fps, recent)
            writer.write(image)
            if frame and frame % 1500 == 0:
                log(f"  rendered frame {frame}/{end}")
    finally:
        cap.release()
        writer.release()
    return out


SUPPRESSED_LABEL = {"initial_on_approach": " (init)", "initial_in_junction": " (init)",
                    "already_entered": " SUPPRESSED (already entered)"}


def _apply(t, colour: dict, recent: list[str], fps: float) -> None:
    kind, arm = gate_kind(t.gate_id), gate_arm(t.gate_id)
    if t.suppressed != "already_entered":  # a suppressed second entry keeps the track's origin colour
        colour[t.track_id] = EXITED if kind == "out" else ARM_COLOURS[arm]
    name = {"in.far": "approach_entered", "in.stop": "intersection_entered", "out": "intersection_exited"}[kind]
    recent.append(f"{time_s(t.frame, fps):7.2f}s #{t.track_id} {name} {arm}" + SUPPRESSED_LABEL.get(t.suppressed, ""))
    del recent[:-EVENT_LINES]


def _panel(image: np.ndarray, run: GateRun, frame: int, fps: float, recent: list[str]) -> None:
    import cv2

    second = min(int(frame / fps + 1e-9), len(run.counts) - 1)
    line = run.counts[second]
    rows = [f"t {frame / fps:6.2f} s  frame {frame}   counts.jsonl t_s={line['t_s']:.0f}",
            "arm    on_appr  entered  discharged"]
    for arm in ARMS:
        a = line["approaches"].get(arm)
        rows.append(f"{arm:<6} {'-':>7}" if a is None else
                    f"{arm:<6} {a['vehicles_on_approach']:>7}  {a['entered_total']:>7}  {a['discharged_total']:>10}")
    junction = line["in_intersection"]
    rows.append(f"in_intersection: {'unknown' if junction is None else junction}")
    rows.append("")
    rows.extend(recent)
    font, fs, lh = cv2.FONT_HERSHEY_SIMPLEX, 0.45, 17
    w = 360
    h = 8 + lh * len(rows)
    overlay = image.copy()
    cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.65, image, 0.35, 0, dst=image)
    for i, text in enumerate(rows):
        c = (255, 255, 255)
        if 2 <= i < 2 + len(ARMS):
            c = ARM_COLOURS[ARMS[i - 2]]
        cv2.putText(image, text, (6, 16 + i * lh), font, fs, c, 1, cv2.LINE_AA)


__all__ = ["render_gate_demo"]
