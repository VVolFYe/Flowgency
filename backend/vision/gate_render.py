"""Gate mode demo video: tracks, gates flashing on triggers, and the published counts.

The panel shows the ``counts.jsonl`` line consumers would read at that moment (the last whole second
``t_s <= frame / fps``), so the demo shows exactly what is published, including its up-to-1-s lag and the
unknown values before the warm-up. Gates flash white for a few frames when a track triggers them (suppressed
triggers too). Box colour: the arm of the track's latest approach or intersection entry, grey after
``intersection_exited``, red after ``approach_left``; before any event, from the warm-up frame on, its arm if it is
in the warm-up offset, white if it was in the junction, else green.

Static vehicles are drawn thin in a muted slate colour, decided causally per frame (:func:`is_static`): the
counting point is outside every approach region, the junction and every gate, and has stayed within
``STATIC_RADIUS_PX`` for the last ``STATIC_WINDOW_S`` (parked cars, mostly). Display only; counting never uses it.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

from .draw_gates import ARM_COLOURS, draw_gates
from .gate_pipeline import TrackedFrame
from .gates import GateRun, Locator, _GateIndex, time_s
from .geometry import Point
from .scene import ARMS, SceneConfig

FLASH_FRAMES = 8
EVENT_LINES = 6
NO_EVENT = (80, 255, 80)
EXITED = (170, 170, 170)
LEFT = (90, 90, 230)  # BGR: left the approach without a discharge
STATIC = (110, 90, 75)  # BGR muted slate
STATIC_WINDOW_S = 3.0
STATIC_RADIUS_PX = 15.0


def is_static(history: Sequence[tuple[int, Point]], frame: int, fps: float, where: str | None, in_gate: bool,
              window_s: float = STATIC_WINDOW_S, radius_px: float = STATIC_RADIUS_PX) -> bool:
    """Display rule from frames <= ``frame`` only: outside all regions/gates and still for the last ``window_s``.

    ``history``: the track's ``(frame, point)`` observations up to ``frame`` (oldest first). The track must have
    been observed at least ``window_s`` ago, so a newly detected moving car is not muted.
    """
    if where is not None or in_gate or not history or frame - history[0][0] < window_s * fps:
        return False
    now = history[-1][1]
    start = frame - window_s * fps
    return all(math.dist(p, now) <= radius_px for f, p in history if f >= start)


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
    events_at: dict[int, list[dict]] = {}
    for e in run.events:
        events_at.setdefault(e["frame"], []).append(e)
    end = len(tracked) if end_frame is None else min(end_frame, len(tracked))
    width, height = (round(v * scale) for v in scene.frame_size)
    locator, gates = Locator(scene), _GateIndex(scene)
    keep = round(STATIC_WINDOW_S * fps) + 1
    history: dict[int, deque] = {}
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    flash: dict[str, int] = {}
    colour: dict[int, tuple[int, int, int]] = {}
    recent: list[str] = []
    # replay events and track history before start_frame so colours, the event list and the static rule are right
    for frame in range(0, start_frame):
        _warm_up_colours(run, frame, colour)
        for e in events_at.get(frame, ()):
            _apply(e, colour, recent)
        tf = by_frame.get(frame)
        for box in tf.boxes if tf else ():
            history.setdefault(box.track_id, deque(maxlen=keep)).append((frame, box.point(scene.counting_point)))
    try:
        for frame in range(start_frame, end):
            ok, image = cap.read()
            if not ok:
                break
            image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
            for t in triggers_at.get(frame, ()):
                flash[t.gate_id] = FLASH_FRAMES
            _warm_up_colours(run, frame, colour)
            for e in events_at.get(frame, ()):
                _apply(e, colour, recent)
            draw_gates(image, scene, scale, flashes=flash, labels=False)
            flash = {g: n - 1 for g, n in flash.items() if n > 1}
            tf = by_frame.get(frame)
            static_now = 0
            for box in tf.boxes if tf else ():
                point = box.point(scene.counting_point)
                h = history.setdefault(box.track_id, deque(maxlen=keep))
                h.append((frame, point))
                x1, y1, x2, y2 = (int(round(v * scale)) for v in box.bbox)
                if is_static(h, frame, fps, locator.locate(point), bool(gates.inside(point))):
                    static_now += 1
                    cv2.rectangle(image, (x1, y1), (x2, y2), STATIC, 1)
                    continue
                c = colour.get(box.track_id, NO_EVENT)
                cv2.rectangle(image, (x1, y1), (x2, y2), c, 2)
                cv2.circle(image, (int(point[0] * scale), int(point[1] * scale)), 3, c, -1)
                cv2.putText(image, str(box.track_id), (x1, max(y1 - 3, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                            (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(image, str(box.track_id), (x1, max(y1 - 3, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, c, 1,
                            cv2.LINE_AA)
            _panel(image, run, frame, fps, recent, static_now)
            writer.write(image)
            if frame and frame % 1500 == 0:
                log(f"  rendered frame {frame}/{end}")
    finally:
        cap.release()
        writer.release()
    return out


def _warm_up_colours(run: GateRun, frame: int, colour: dict) -> None:
    """From the warm-up frame on (when the offset is decided), colour the offset vehicles."""
    if frame == run.initial.warmup_frame:
        colour.update({tid: ARM_COLOURS[arm] for arm, ids in run.initial.approach_tracks.items() for tid in ids})
        colour.update({tid: (255, 255, 255) for tid in run.initial.junction_tracks or ()})


def _apply(e: dict, colour: dict, recent: list[str]) -> None:
    event, arm, tid = e["event"], e["arm"], e["track_id"]
    if event == "intersection_exited":
        colour[tid] = EXITED
    elif event == "approach_left":
        colour[tid] = LEFT
    else:
        colour[tid] = ARM_COLOURS[arm]
    via = f" via {e['via']}" if e.get("via") not in (None, "far_gate") else ""
    recent.append(f"{e['t_s']:7.2f}s #{tid} {event} {arm}{via}")
    del recent[:-EVENT_LINES]


def _panel(image: np.ndarray, run: GateRun, frame: int, fps: float, recent: list[str], static_now: int) -> None:
    import cv2

    second = min(int(frame / fps + 1e-9), len(run.counts) - 1)
    line = run.counts[second]
    rows = [f"t {frame / fps:6.2f} s  frame {frame}   counts.jsonl t_s={line['t_s']:.0f}",
            "arm    on_appr entered disch left"]
    for arm in ARMS:
        a = line["approaches"].get(arm)
        rows.append(f"{arm:<6} {'-':>7}" if a is None else
                    f"{arm:<6} {a['vehicles_on_approach']:>7} {a['entered_total']:>7} {a['discharged_total']:>5} "
                    f"{a.get('left_total') or 0:>4}")
    junction = line["in_intersection"]
    rows.append(f"in_intersection: {'unknown' if junction is None else junction}")
    if not line["approaches"]:
        rows.append(f"warm-up: counts unknown until {time_s(run.initial.warmup_frame, fps):g} s")
    rows.append(f"thin slate = static off-lane ({static_now}), display only")
    rows.append("")
    rows.extend(recent)
    font, fs, lh = cv2.FONT_HERSHEY_SIMPLEX, 0.45, 17
    w = 380
    h = 8 + lh * len(rows)
    overlay = image.copy()
    cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.65, image, 0.35, 0, dst=image)
    for i, text in enumerate(rows):
        c = (255, 255, 255)
        if 2 <= i < 2 + len(ARMS):
            c = ARM_COLOURS[ARMS[i - 2]]
        elif text.startswith("thin slate"):
            c = (200, 175, 155)
        cv2.putText(image, text, (6, 16 + i * lh), font, fs, c, 1, cv2.LINE_AA)


__all__ = ["is_static", "render_gate_demo"]
