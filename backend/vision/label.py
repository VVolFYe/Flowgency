"""Manual ground-truth labelling tool (``cli label``).

Plays each eval-set clip in a loop with the approach lines and inbound arrows
drawn but **no model output** (no boxes, no counts), so labels are unbiased.
Only the frames the pipeline analyses are shown (a trimmed corrupt start is
excluded), so ground truth and predictions cover the same window.

For each approach, count vehicles whose road contact point (where the wheels
touch the road) crosses the line in the arrow direction within the line's
extent. Type the total, optionally with a class split: ``3`` or
``3 car=2 bus=1`` (unlisted classes = 0; the split must add up). Mark a clip
unusable with ``x`` and a reason. Progress is saved after every clip.

Keys never used in entries drive playback: ``p`` pause/play, ``,``/``.``
step back/forward, ``[``/``]`` slower/faster (0.25x-1x), ``z`` restart,
``x`` unusable, ``w`` previous clip, ``q`` quit, Esc clears the field.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .counting import VEHICLE_CLASSES
from .evaluation import parse_count_entry

SPEEDS = (0.25, 0.5, 0.75, 1.0)
KEY_ENTER = (10, 13)
KEY_BACKSPACE = (8, 127)
KEY_ESC = 27
ENTRY_CHARS = set("0123456789 =") | set("".join(VEHICLE_CLASSES))
CONTROL_KEYS = set("p,.[]zxwq")
assert not (ENTRY_CHARS & CONTROL_KEYS), "control keys must not collide with entry characters"


@dataclass
class ClipLabelState:
    """Pure keyboard state machine for labelling one clip."""

    approaches: list[str]
    entries: dict[str, tuple[int, dict[str, int] | None]] = field(default_factory=dict)
    current: int = 0
    text: str = ""
    reason_mode: bool = False
    unusable_reason: str | None = None
    message: str = ""
    action: str | None = None  # None | "save" | "back" | "quit"

    @property
    def done(self) -> bool:
        return self.unusable_reason is not None or len(self.entries) == len(self.approaches)

    def prompt(self) -> str:
        if self.reason_mode:
            return f"unusable reason: {self.text}_  (Enter=save, Esc=cancel)"
        approach = self.approaches[self.current]
        return f"{approach} inbound crossings: {self.text}_  (e.g. 3 or 3 car=2 bus=1)"

    def key(self, code: int) -> None:
        self.action = None
        char = chr(code) if 32 <= code < 127 else ""
        if self.reason_mode:
            self._reason_key(code, char)
            return
        if code in KEY_ENTER:
            self._submit()
        elif code in KEY_BACKSPACE:
            self.text = self.text[:-1]
        elif code == KEY_ESC:
            self.text = ""
        elif char == "x":
            self.reason_mode, self.text = True, ""
        elif char == "w":
            self.action = "back"
        elif char == "q":
            self.action = "quit"
        elif char in ENTRY_CHARS and len(self.text) < 60:
            self.text += char

    def _reason_key(self, code: int, char: str) -> None:
        if code in KEY_ENTER:
            if not self.text.strip():
                self.message = "type a reason (e.g. view blocked, too dark)"
                return
            self.unusable_reason = self.text.strip()
            self.action = "save"
        elif code == KEY_ESC:
            self.reason_mode, self.text = False, ""
        elif code in KEY_BACKSPACE:
            self.text = self.text[:-1]
        elif char and len(self.text) < 120:
            self.text += char

    def _submit(self) -> None:
        try:
            total, split = parse_count_entry(self.text)
        except ValueError as exc:
            self.message = str(exc)
            return
        approach = self.approaches[self.current]
        self.entries[approach] = (total, split)
        self.text, self.message = "", f"{approach} = {total}"
        if self.current + 1 < len(self.approaches):
            self.current += 1
        else:
            self.action = "save"


def ground_truth_rows(eval_row: dict[str, str], state: ClipLabelState, now: datetime | None = None) -> list[dict[str, Any]]:
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = {k: eval_row[k] for k in ("intersection_id", "camera_id", "clip", "observed_at_utc", "period")}
    rows = []
    for approach in state.approaches:
        row = {**base, "approach_id": approach, "labelled_at_utc": stamp, "reason": "", "total": ""}
        row.update({c: "" for c in VEHICLE_CLASSES})
        if state.unusable_reason is not None:
            row.update(status="unusable", reason=state.unusable_reason)
        else:
            total, split = state.entries[approach]
            row.update(status="labelled", total=total)
            if split:
                row.update(split)
        rows.append(row)
    return rows


def is_complete(rows: list[dict[str, str]], approaches: list[str]) -> bool:
    if any(r["status"] == "unusable" for r in rows):
        return True
    return {r["approach_id"] for r in rows if r["status"] == "labelled"} >= set(approaches)


# --- GUI --------------------------------------------------------------------------------


@dataclass
class LabelItem:
    eval_row: dict[str, str]
    camera: Any  # CameraConfig
    frames: Callable[[], list[Any]]  # loads the analysed frames lazily
    existing: list[dict[str, str]]


def run_label_gui(items: list[LabelItem], save_rows: Callable[[dict[str, str], list[dict[str, Any]]], None],
                  start: int = 0, scale: int = 3, fps: float = 25.0) -> None:
    import cv2
    import numpy as np

    from .draw_lines import draw_approaches

    window = "label (no model output shown)"
    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE | cv2.WINDOW_GUI_NORMAL)
    position = start
    while 0 <= position < len(items):
        item = items[position]
        frames = item.frames()
        state = ClipLabelState(item.camera.approach_ids)
        if item.existing:  # revisiting: show what was saved; entering new values overwrites it
            previous = ", ".join(
                f"{r['approach_id']}={r['total']}" if r["status"] == "labelled" else f"unusable ({r['reason']})"
                for r in item.existing
            )
            state.message = f"saved before: {previous}. Re-enter to overwrite, or w/q"
        index, speed_i, playing = 0, 1, True
        while True:
            frame = frames[index] if frames else np.zeros((288, 352, 3), np.uint8)
            view = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            counts = {a: v[0] for a, v in state.entries.items()}
            draw_approaches(view, item.camera.approaches, scale, counts=counts if counts else None)
            width = view.shape[1]
            top = np.zeros((70, width, 3), np.uint8)
            row = item.eval_row
            cv2.putText(top, f"[{position + 1}/{len(items)}] {row['intersection_id']} {row['camera_id']} {row['clip']} "
                             f"({row['observed_at_utc']}, {row['period']})", (8, 20), 0, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(top, f"frame {index + 1}/{len(frames)}  speed {SPEEDS[speed_i]}x  {'PLAYING' if playing else 'PAUSED'}   "
                             "count contact point crossing the line in the arrow direction", (8, 42), 0, 0.45,
                        (200, 200, 200), 1, cv2.LINE_AA)
            cv2.putText(top, state.message, (8, 62), 0, 0.45, (0, 200, 255), 1, cv2.LINE_AA)
            bottom = np.zeros((60, width, 3), np.uint8)
            cv2.putText(bottom, state.prompt(), (8, 22), 0, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(bottom, "p play/pause  ,/. step  [/] speed  z restart  x unusable  w previous clip  q quit",
                        (8, 48), 0, 0.42, (180, 180, 180), 1, cv2.LINE_AA)
            cv2.imshow(window, np.vstack([top, view, bottom]))
            delay = max(1, int(1000 / (fps * SPEEDS[speed_i]))) if playing else 50
            code = cv2.waitKey(delay)
            if code == -1:
                if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                    return
                if playing and frames:
                    index = (index + 1) % len(frames)
                continue
            code &= 0xFF
            char = chr(code) if 32 <= code < 127 else ""
            if not state.reason_mode and char in "p,.[]z":
                if char == "p":
                    playing = not playing
                elif char == ",":
                    playing, index = False, max(index - 1, 0)
                elif char == ".":
                    playing, index = False, min(index + 1, len(frames) - 1)
                elif char == "[":
                    speed_i = max(speed_i - 1, 0)
                elif char == "]":
                    speed_i = min(speed_i + 1, len(SPEEDS) - 1)
                elif char == "z":
                    index = 0
                continue
            state.key(code)
            if state.action == "save":
                save_rows(item.eval_row, ground_truth_rows(item.eval_row, state))
                position += 1
                break
            if state.action == "back":
                position = max(position - 1, 0)
                break
            if state.action == "quit":
                cv2.destroyWindow(window)
                return
    cv2.destroyWindow(window)
