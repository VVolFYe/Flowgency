"""Interactive counting-line editor (``cli draw-lines``).

Flow per approach: press ``a``, type the approach ID (``<compass>bound_in``),
press Enter, click the two line endpoints across the lanes near the stop line,
then click a third point on the side vehicles drive *towards* (the inbound
direction). An arrow shows that direction; Enter accepts, ``r`` re-clicks.

``s`` saves the camera to ``cameras.json`` and the currently displayed frame as
its reference frame (JPEG under ``UNIHACK_DIR/vision_output/reference_frames``).
The editor logic is pure; only :func:`run_draw_lines` opens a window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .config import ApproachConfig, CameraConfig, CamerasConfig, validate_approach_id

Point = tuple[float, float]

KEY_ENTER = (10, 13)
KEY_ESC = 27
KEY_BACKSPACE = (8, 127)


class Mode(Enum):
    BROWSE = "browse"
    TYPING = "typing"
    POINTS = "points"
    CONFIRM = "confirm"


@dataclass
class ApproachEditor:
    """Pure state machine for adding/removing approaches on one camera."""

    frame_size: tuple[int, int]
    approaches: list[ApproachConfig] = field(default_factory=list)
    mode: Mode = Mode.BROWSE
    text: str = ""
    points: list[Point] = field(default_factory=list)
    message: str = ""
    dirty: bool = False

    # --- events -----------------------------------------------------------
    def start_approach(self) -> None:
        self.mode, self.text, self.points = Mode.TYPING, "", []
        self.message = "Type approach ID (e.g. southbound_in), Enter to confirm, Esc to cancel"

    def key(self, code: int) -> None:
        if self.mode is Mode.TYPING:
            self._typing_key(code)
        elif self.mode in (Mode.POINTS, Mode.CONFIRM):
            if code == KEY_ESC:
                self.cancel()
            elif self.mode is Mode.CONFIRM and code in KEY_ENTER:
                self._accept()
            elif code == ord("r"):
                self.points = []
                self.mode = Mode.POINTS
                self.message = self._points_prompt()

    def click(self, x: float, y: float) -> None:
        if self.mode is not Mode.POINTS:
            return
        width, height = self.frame_size
        point = (round(min(max(x, 0.0), width), 1), round(min(max(y, 0.0), height), 1))
        self.points.append(point)
        if len(self.points) == 3:
            try:
                self._candidate()
            except ValueError as exc:
                self.points = []
                self.message = f"Invalid geometry ({_first_line(exc)}); click the line again"
                return
            self.mode = Mode.CONFIRM
            self.message = "Check the arrow points INTO the intersection. Enter=accept, r=redo, Esc=cancel"
        else:
            self.message = self._points_prompt()

    def cancel(self) -> None:
        self.mode, self.text, self.points = Mode.BROWSE, "", []
        self.message = "Cancelled"

    def delete_last(self) -> None:
        if self.mode is Mode.BROWSE and self.approaches:
            removed = self.approaches.pop()
            self.dirty = True
            self.message = f"Removed {removed.approach_id}"

    # --- helpers ----------------------------------------------------------
    def _typing_key(self, code: int) -> None:
        if code == KEY_ESC:
            self.cancel()
        elif code in KEY_BACKSPACE:
            self.text = self.text[:-1]
        elif code in KEY_ENTER:
            try:
                validate_approach_id(self.text)
            except ValueError as exc:
                self.message = str(exc)
                return
            if self.text in {a.approach_id for a in self.approaches}:
                self.message = f"{self.text} already exists; press x to delete it first"
                return
            self.mode, self.points = Mode.POINTS, []
            self.message = self._points_prompt()
        elif 32 <= code < 127 and len(self.text) < 40:
            self.text += chr(code).lower()

    def _points_prompt(self) -> str:
        return (
            f"{self.text}: click line endpoint 1 (across the lanes, near the stop line)",
            f"{self.text}: click line endpoint 2",
            f"{self.text}: click a point on the side vehicles drive TOWARDS (inbound)",
        )[len(self.points)]

    def _candidate(self) -> ApproachConfig:
        p1, p2, inbound = self.points
        return ApproachConfig(approach_id=self.text, line=(p1, p2), inbound_point=inbound)

    def _accept(self) -> None:
        approach = self._candidate()
        self.approaches.append(approach)
        self.dirty = True
        self.mode, self.text, self.points = Mode.BROWSE, "", []
        self.message = f"Added {approach.approach_id}; a=add another, s=save"

    def build_camera(self, intersection_id: str, camera_id: str, reference_frame: str | None) -> CameraConfig:
        return CameraConfig(
            intersection_id=intersection_id,
            camera_id=camera_id,
            frame_size=self.frame_size,
            reference_frame=reference_frame,
            approaches=tuple(self.approaches),
        )


def _first_line(exc: Exception) -> str:
    text = str(exc).splitlines()
    return text[-1].strip() if text else type(exc).__name__


# --- drawing (shared with render-demo and label) ---------------------------


def inbound_arrow(line: tuple[Point, Point], inbound_point: Point, length: float = 22.0) -> tuple[Point, Point]:
    """Arrow from the line midpoint, perpendicular to it, towards the inbound side."""
    (x1, y1), (x2, y2) = line
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    nx, ny = -(y2 - y1), x2 - x1
    norm = (nx * nx + ny * ny) ** 0.5 or 1.0
    nx, ny = nx / norm, ny / norm
    if (inbound_point[0] - mx) * nx + (inbound_point[1] - my) * ny < 0:
        nx, ny = -nx, -ny
    return (mx, my), (mx + nx * length, my + ny * length)


APPROACH_COLOURS = [(0, 220, 255), (255, 160, 0), (80, 255, 80), (255, 80, 255), (0, 120, 255), (255, 255, 80)]


def draw_approaches(
    image: Any,
    approaches: list[ApproachConfig] | tuple[ApproachConfig, ...],
    scale: float,
    counts: dict[str, int] | None = None,
) -> None:
    import cv2

    def sp(p: Point) -> tuple[int, int]:
        return int(round(p[0] * scale)), int(round(p[1] * scale))

    thickness = max(1, int(round(scale)))
    for index, approach in enumerate(approaches):
        colour = APPROACH_COLOURS[index % len(APPROACH_COLOURS)]
        p1, p2 = approach.line
        cv2.line(image, sp(p1), sp(p2), (0, 0, 0), thickness + 2, cv2.LINE_AA)
        cv2.line(image, sp(p1), sp(p2), colour, thickness, cv2.LINE_AA)
        start, end = inbound_arrow(approach.line, approach.inbound_point)
        cv2.arrowedLine(image, sp(start), sp(end), colour, thickness, cv2.LINE_AA, tipLength=0.35)
        label = approach.approach_id if counts is None else f"{approach.approach_id}: {counts.get(approach.approach_id, 0)}"
        _label(image, label, (sp(p2)[0] + 6, sp(p2)[1] - 6), colour, 0.35 * scale)


def _label(image: Any, text: str, origin: tuple[int, int], colour: tuple[int, int, int], font_scale: float) -> None:
    import cv2

    font_scale = max(font_scale, 0.4)
    thick = max(1, int(font_scale * 2))
    (w, h), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thick)
    x = min(max(origin[0], 0), image.shape[1] - w - 2)
    y = min(max(origin[1], h + 2), image.shape[0] - base - 2)
    cv2.rectangle(image, (x - 2, y - h - 2), (x + w + 2, y + base + 1), (0, 0, 0), -1)
    cv2.putText(image, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, colour, thick, cv2.LINE_AA)


HELP = (
    "n/p next/prev clip   ./, next/prev frame   >/< +-25 frames   a add approach   x delete last   "
    "s save   q quit"
)
BAR = 46


def render(editor: ApproachEditor, frame: Any, scale: int, status: str) -> Any:
    """Compose the editor view: info bar, upscaled frame with overlays, help bar."""
    import cv2
    import numpy as np

    view = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    draw_approaches(view, editor.approaches, scale)
    pts = [(int(x * scale), int(y * scale)) for x, y in editor.points]
    for p in pts:
        cv2.circle(view, p, 5, (0, 0, 255), -1, cv2.LINE_AA)
    if len(pts) >= 2:
        cv2.line(view, pts[0], pts[1], (0, 0, 255), 2, cv2.LINE_AA)
    if editor.mode is Mode.CONFIRM:
        start, end = inbound_arrow((editor.points[0], editor.points[1]), editor.points[2])
        cv2.arrowedLine(
            view, (int(start[0] * scale), int(start[1] * scale)), (int(end[0] * scale), int(end[1] * scale)),
            (0, 0, 255), 3, cv2.LINE_AA, tipLength=0.35,
        )
    width = view.shape[1]
    top = np.zeros((BAR, width, 3), np.uint8)
    bottom = np.zeros((BAR, width, 3), np.uint8)
    cv2.putText(top, status, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    line2 = f"> {editor.text}_" if editor.mode is Mode.TYPING else editor.message
    cv2.putText(top, line2, (8, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(bottom, HELP, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1, cv2.LINE_AA)
    unsaved = "UNSAVED CHANGES" if editor.dirty else "saved"
    cv2.putText(bottom, f"{len(editor.approaches)} approach(es) - {unsaved}", (8, 38),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255) if editor.dirty else (120, 220, 120), 1, cv2.LINE_AA)
    return np.vstack([top, view, bottom])


# --- GUI loop -------------------------------------------------------------------


def default_start_index(clips: list[Any], day_hours: range = range(8, 16)) -> int:
    """Latest daytime (UTC) clip, else the latest clip."""
    for index in range(len(clips) - 1, -1, -1):
        if clips[index].observed_at_utc.hour in day_hours:
            return index
    return len(clips) - 1


def run_draw_lines(
    *,
    camera_id: str,
    intersection_id: str,
    clips: list[Any],
    config: CamerasConfig,
    config_path: Path,
    reference_dir: Path,
    to_relative: Any,
    start_clip: str | None = None,
    scale: int = 3,
) -> None:
    import cv2

    from .clips import format_utc, read_frames
    from .config import save_cameras

    if not clips:
        raise SystemExit(f"no clips found for {camera_id}")
    index = default_start_index(clips)
    if start_clip:
        names = [c.name for c in clips]
        if start_clip not in names:
            raise SystemExit(f"clip {start_clip} not found for {camera_id}")
        index = names.index(start_clip)

    existing = next((c for c in config.cameras if c.camera_id == camera_id), None)
    frames = read_frames(clips[index].path)
    frame_index = 0
    height, width = frames[0].shape[:2] if frames else (288, 352)
    editor = ApproachEditor((width, height), list(existing.approaches) if existing else [])
    if existing and tuple(existing.frame_size) != (width, height):
        editor.message = f"WARNING: configured frame size {existing.frame_size} != clip {width}x{height}"
    quit_armed = False

    window = f"draw-lines {camera_id}"
    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE | cv2.WINDOW_GUI_NORMAL)

    def on_mouse(event: int, x: int, y: int, *_: Any) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and BAR <= y < BAR + height * scale:
            editor.click(x / scale, (y - BAR) / scale)

    cv2.setMouseCallback(window, on_mouse)

    def load(new_index: int) -> None:
        nonlocal index, frames, frame_index
        index = new_index % len(clips)
        frames = read_frames(clips[index].path) or frames
        frame_index = min(frame_index, len(frames) - 1)

    while True:
        clip = clips[index]
        status = (
            f"{intersection_id} {camera_id} | clip {index + 1}/{len(clips)} {clip.name} "
            f"({format_utc(clip.observed_at_utc)}) | frame {frame_index + 1}/{len(frames)}"
        )
        if not frames:
            status += " | UNREADABLE CLIP"
            frame = None
        else:
            frame = frames[frame_index]
        if frame is not None:
            cv2.imshow(window, render(editor, frame, scale, status))
        code = cv2.waitKey(30)
        if code == -1:
            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
            continue
        code &= 0xFF
        if editor.mode is not Mode.BROWSE:
            editor.key(code)
            continue
        if code != ord("q") and code != KEY_ESC:
            quit_armed = False
        if code in (ord("q"), KEY_ESC):
            if editor.dirty and not quit_armed:
                editor.message = "Unsaved changes: press q again to quit without saving, s to save"
                quit_armed = True
                continue
            break
        elif code == ord("n"):
            load(index + 1)
        elif code == ord("p"):
            load(index - 1)
        elif code == ord("."):
            frame_index = min(frame_index + 1, len(frames) - 1)
        elif code == ord(","):
            frame_index = max(frame_index - 1, 0)
        elif code == ord(">"):
            frame_index = min(frame_index + 25, len(frames) - 1)
        elif code == ord("<"):
            frame_index = max(frame_index - 25, 0)
        elif code == ord("a"):
            editor.start_approach()
        elif code == ord("x"):
            editor.delete_last()
        elif code == ord("s"):
            if frame is None:
                editor.message = "Cannot save: current clip is unreadable"
                continue
            if not editor.approaches:
                editor.message = "Add at least one approach before saving"
                continue
            reference_dir.mkdir(parents=True, exist_ok=True)
            ref_path = reference_dir / f"{camera_id}__{clip.name}_f{frame_index:03d}.jpg"
            cv2.imwrite(str(ref_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            camera = editor.build_camera(intersection_id, camera_id, to_relative(ref_path))
            config.upsert(camera)
            save_cameras(config, config_path)
            editor.dirty = False
            editor.message = f"Saved {len(camera.approaches)} approach(es); reference {ref_path.name}"
    cv2.destroyWindow(window)
