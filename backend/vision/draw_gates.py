"""Interactive gate editor (``cli draw-gates``).

Pick a gate ID in the list on the right (click it, or ``n``/``p``), click its
4 corners on the frame in order around the gate, and the editor moves on to
the next missing gate. All gates drawn so far stay visible; ``r`` redoes the
selected gate, ``s`` saves. Overlaps, missing gates, and thin gates are listed
as warnings (saving is still allowed so work can be resumed).

The editor logic (:class:`GateEditor`) is pure; only :func:`run_draw_gates`
opens a window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .geometry import Point, centroid
from .scene import ARMS, GATE_IDS, SceneConfig, gate_arm, gate_kind, validate_gate_polygon

KEY_ESC = 27

ARM_COLOURS = {  # BGR
    "north": (0, 220, 255),
    "east": (255, 160, 0),
    "south": (80, 255, 80),
    "west": (255, 80, 255),
}
KIND_LABEL = {"in.far": "far", "in.stop": "stop", "out": "out"}


@dataclass
class GateEditor:
    """Pure state machine for drawing the 12 gates of one scene."""

    frame_size: tuple[int, int]
    gates: dict[str, tuple[Point, ...]] = field(default_factory=dict)
    selected: str = GATE_IDS[0]
    points: list[Point] = field(default_factory=list)
    message: str = ""
    dirty: bool = False

    def __post_init__(self) -> None:
        missing = self.missing()
        self.selected = missing[0] if missing else GATE_IDS[0]
        self.message = self._prompt()

    def missing(self) -> list[str]:
        return [g for g in GATE_IDS if g not in self.gates]

    def select(self, gate_id: str) -> None:
        if gate_id not in GATE_IDS:
            self.message = f"unknown gate {gate_id!r}"
            return
        self.selected, self.points = gate_id, []
        self.message = self._prompt()

    def step(self, delta: int) -> None:
        self.select(GATE_IDS[(GATE_IDS.index(self.selected) + delta) % len(GATE_IDS)])

    def click(self, x: float, y: float) -> None:
        width, height = self.frame_size
        self.points.append((round(min(max(x, 0.0), width), 1), round(min(max(y, 0.0), height), 1)))
        if len(self.points) < 4:
            self.message = self._prompt()
            return
        polygon = tuple(self.points)
        self.points = []
        try:
            validate_gate_polygon(self.selected, polygon, self.frame_size)
        except ValueError as exc:
            self.message = f"Rejected: {exc}. Click the 4 corners again"
            return
        self.gates[self.selected] = polygon
        self.dirty = True
        done = self.selected
        missing = self.missing()
        if missing:
            after = [g for g in missing if GATE_IDS.index(g) > GATE_IDS.index(done)]
            self.selected = (after or missing)[0]
            self.message = f"Saved {done} in memory. Now: {self._prompt()}"
        else:
            self.message = f"Saved {done} in memory. All 12 gates drawn: press s to save the file"

    def undo_point(self) -> None:
        if self.points:
            self.points.pop()
            self.message = self._prompt()

    def redo(self) -> None:
        """Forget the selected gate's polygon and start clicking it again."""
        if self.gates.pop(self.selected, None) is not None:
            self.dirty = True
        self.points = []
        self.message = f"Redo {self.selected}: {self._prompt()}"

    def delete(self) -> None:
        if self.gates.pop(self.selected, None) is not None:
            self.dirty = True
            self.message = f"Deleted {self.selected}"
        self.points = []

    def cancel_points(self) -> bool:
        if not self.points:
            return False
        self.points = []
        self.message = f"Cancelled. {self._prompt()}"
        return True

    def _prompt(self) -> str:
        corner = len(self.points) + 1
        hint = {
            "in.far": "across the INBOUND lanes at the frame edge",
            "in.stop": "across the INBOUND lanes just past the stop line",
            "out": "across the OUTBOUND lanes just past the crosswalk",
        }[gate_kind(self.selected)]
        redo = " (already drawn: r to redo)" if self.selected in self.gates and not self.points else ""
        return f"{self.selected}{redo}: click corner {corner}/4, {hint}"

    def build_scene(self, base: SceneConfig, reference_frame_index: int | None) -> SceneConfig:
        data = base.model_dump()
        data["gates"] = dict(self.gates)
        data["reference_frame_index"] = reference_frame_index
        return SceneConfig.model_validate(data)


# --- drawing (shared with the gate-mode renderer) ----------------------------


def draw_gates(
    image: Any,
    scene_or_gates: SceneConfig | dict[str, tuple[Point, ...]],
    scale: float,
    *,
    selected: str | None = None,
    flashes: dict[str, int] | None = None,
    show_regions: bool = False,
    frame_size: tuple[int, int] | None = None,
    labels: bool = True,
) -> None:
    import cv2
    import numpy as np

    if isinstance(scene_or_gates, SceneConfig):
        scene = scene_or_gates
    else:
        scene = SceneConfig.model_construct(gates=dict(scene_or_gates), frame_size=frame_size or (1, 1))
    gates = scene.gates

    def sp(poly) -> Any:
        return np.array([[int(round(x * scale)), int(round(y * scale))] for x, y in poly], np.int32)

    if show_regions:
        overlay = image.copy()
        for arm, region in scene.approach_regions().items():
            cv2.fillPoly(overlay, [sp(region)], ARM_COLOURS[arm])
        junction = scene.junction_region()
        if junction is not None:
            cv2.polylines(image, [sp(junction)], True, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.18, image, 0.82, 0, dst=image)
    for gate_id, poly in gates.items():
        colour = ARM_COLOURS[gate_arm(gate_id)]
        pts = sp(poly)
        flashing = bool(flashes and flashes.get(gate_id, 0) > 0)
        if flashing or gate_id == selected:
            overlay = image.copy()
            cv2.fillPoly(overlay, [pts], (255, 255, 255) if flashing else colour)
            cv2.addWeighted(overlay, 0.55 if flashing else 0.3, image, 0.45 if flashing else 0.7, 0, dst=image)
        thick = 3 if gate_kind(gate_id) == "in.stop" else 2
        cv2.polylines(image, [pts], True, (0, 0, 0), thick + 2, cv2.LINE_AA)
        cv2.polylines(image, [pts], True, (255, 255, 255) if flashing else colour, thick, cv2.LINE_AA)
        if labels:
            cx, cy = centroid(poly)
            text = f"{gate_arm(gate_id)[0].upper()} {KIND_LABEL[gate_kind(gate_id)]}"
            _label(image, text, (int(cx * scale) - 14, int(cy * scale) + 5), colour, 0.45)


def _label(image: Any, text: str, origin: tuple[int, int], colour: tuple[int, int, int], font_scale: float) -> None:
    import cv2

    thick = 1
    (w, h), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thick)
    x = min(max(origin[0], 0), image.shape[1] - w - 2)
    y = min(max(origin[1], h + 2), image.shape[0] - base - 2)
    cv2.rectangle(image, (x - 2, y - h - 2), (x + w + 2, y + base + 1), (0, 0, 0), -1)
    cv2.putText(image, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, colour, thick, cv2.LINE_AA)


PANEL_W = 320
ROW_H = 24
LIST_TOP = 34
LOUPE_SRC = 48   # source pixels around the cursor
LOUPE_PX = 200   # displayed size
BAR = 44
HELP_LINES = (
    "click list / n p : pick gate",
    "left click: add corner (4 per gate)",
    "right click / u : undo corner",
    "r redo gate   x delete gate",
    "Esc cancel corners",
    ", .  -/+1 frame   [ ]  -/+1 s",
    "{ }  -/+10 s",
    "t approach regions on/off",
    "s save   q quit",
)


def render(editor: GateEditor, frame: Any, scale: float, status: str, cursor: Point | None,
           show_regions: bool, warnings: list[str]) -> Any:
    import cv2
    import numpy as np

    width, height = editor.frame_size
    view = cv2.resize(frame, (int(round(width * scale)), int(round(height * scale))), interpolation=cv2.INTER_AREA)
    draw_gates(view, editor.gates, scale, selected=editor.selected, show_regions=show_regions,
               frame_size=editor.frame_size)
    colour = ARM_COLOURS[gate_arm(editor.selected)]
    pts = [(int(round(x * scale)), int(round(y * scale))) for x, y in editor.points]
    for i, p in enumerate(pts):
        cv2.circle(view, p, 4, (0, 0, 255), -1, cv2.LINE_AA)
        if i:
            cv2.line(view, pts[i - 1], p, (0, 0, 255), 1, cv2.LINE_AA)
    if pts and cursor is not None:
        c = (int(round(cursor[0] * scale)), int(round(cursor[1] * scale)))
        cv2.line(view, pts[-1], c, (0, 0, 255), 1, cv2.LINE_AA)
        if len(pts) == 3:
            cv2.line(view, c, pts[0], (0, 0, 255), 1, cv2.LINE_AA)

    panel = np.zeros((view.shape[0], PANEL_W, 3), np.uint8)
    cv2.putText(panel, "GATES (click to select)", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    for i, gate_id in enumerate(GATE_IDS):
        y = LIST_TOP + i * ROW_H
        if gate_id == editor.selected:
            cv2.rectangle(panel, (4, y), (PANEL_W - 4, y + ROW_H - 2), (70, 70, 70), -1)
        done = gate_id in editor.gates
        mark = "[x]" if done else "[ ]"
        cv2.putText(panel, f"{mark} {gate_id}", (10, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.52,
                    ARM_COLOURS[gate_arm(gate_id)] if done else (150, 150, 150), 1, cv2.LINE_AA)
    loupe_top = LIST_TOP + len(GATE_IDS) * ROW_H + 8
    if cursor is not None and loupe_top + LOUPE_PX < panel.shape[0]:
        cx, cy = int(round(cursor[0])), int(round(cursor[1]))
        half = LOUPE_SRC // 2
        padded = cv2.copyMakeBorder(frame, half, half, half, half, cv2.BORDER_CONSTANT)
        crop = padded[cy : cy + LOUPE_SRC, cx : cx + LOUPE_SRC]
        if crop.shape[:2] == (LOUPE_SRC, LOUPE_SRC):
            zoom = cv2.resize(crop, (LOUPE_PX, LOUPE_PX), interpolation=cv2.INTER_NEAREST)
            mid = LOUPE_PX // 2
            cv2.line(zoom, (mid, 0), (mid, LOUPE_PX), colour, 1)
            cv2.line(zoom, (0, mid), (LOUPE_PX, mid), colour, 1)
            x0 = (PANEL_W - LOUPE_PX) // 2
            panel[loupe_top : loupe_top + LOUPE_PX, x0 : x0 + LOUPE_PX] = zoom
            cv2.putText(panel, f"x={cursor[0]:.0f} y={cursor[1]:.0f}", (x0, loupe_top + LOUPE_PX + 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)
    help_top = loupe_top + LOUPE_PX + 34
    for i, line in enumerate(HELP_LINES):
        y = help_top + i * 18
        if y < panel.shape[0] - 4:
            cv2.putText(panel, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (190, 190, 190), 1, cv2.LINE_AA)

    body = np.hstack([view, panel])
    top = np.zeros((BAR, body.shape[1], 3), np.uint8)
    bottom = np.zeros((BAR, body.shape[1], 3), np.uint8)
    cv2.putText(top, status, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(top, editor.message, (8, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    saved = "UNSAVED CHANGES" if editor.dirty else "saved"
    cv2.putText(bottom, f"{len(editor.gates)}/12 gates - {saved}", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (0, 200, 255) if editor.dirty else (120, 220, 120), 1, cv2.LINE_AA)
    warn = f"{len(warnings)} warning(s): " + " | ".join(warnings) if warnings else "no warnings"
    cv2.putText(bottom, warn[:220], (8, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                (80, 160, 255) if warnings else (120, 220, 120), 1, cv2.LINE_AA)
    return np.vstack([top, body, bottom])


def gate_warnings(editor: GateEditor, base: SceneConfig) -> list[str]:
    scene = editor.build_scene(base, base.reference_frame_index)
    return [w for w in scene.warnings() if not w.startswith("missing gates")]


# --- GUI loop -------------------------------------------------------------------


class FrameReader:
    """Random access to one video's frames (cached current frame)."""

    def __init__(self, path: Path) -> None:
        import cv2

        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise SystemExit(f"cannot open video {path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))  # header value; may overstate
        self._index: int | None = None
        self._frame: Any = None

    def get(self, index: int) -> tuple[int, Any]:
        import cv2

        index = max(0, min(index, max(self.count - 1, 0)))
        if index != self._index:
            if self._index is None or index != self._index + 1:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = self.cap.read()
            if not ok:  # header frame count can exceed the decodable frames; step back
                self.count = index
                return self.get(index - 1) if index > 0 else (index, self._frame)
            self._index, self._frame = index, frame
        return self._index, self._frame

    def close(self) -> None:
        self.cap.release()


def run_draw_gates(
    *,
    scene: SceneConfig,
    scene_path: Path,
    video_path: Path,
    preview_path: Path | None,
    scale: float = 0.7,
    start_frame: int | None = None,
) -> None:
    import cv2

    from .scene import save_scene

    reader = FrameReader(video_path)
    index, frame = reader.get(start_frame if start_frame is not None else (scene.reference_frame_index or 0))
    if frame is None:
        raise SystemExit(f"cannot decode a frame from {video_path}")
    height, width = frame.shape[:2]
    if (width, height) != tuple(scene.frame_size):
        raise SystemExit(f"video is {width}x{height} but the scene says {scene.frame_size[0]}x{scene.frame_size[1]}")
    editor = GateEditor((width, height), {g: tuple(p) for g, p in scene.gates.items()})
    show_regions = False
    cursor: Point | None = None
    quit_armed = False
    view_w, view_h = int(round(width * scale)), int(round(height * scale))

    window = f"draw-gates {scene.scene_id}"
    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE | cv2.WINDOW_GUI_NORMAL)

    def on_mouse(event: int, x: int, y: int, *_: Any) -> None:
        nonlocal cursor
        inside_view = 0 <= x < view_w and BAR <= y < BAR + view_h
        if event == cv2.EVENT_MOUSEMOVE:
            cursor = (x / scale, (y - BAR) / scale) if inside_view else cursor
        elif event == cv2.EVENT_LBUTTONDOWN:
            if inside_view:
                editor.click(x / scale, (y - BAR) / scale)
            elif x >= view_w:
                row = (y - BAR - LIST_TOP) // ROW_H
                if 0 <= row < len(GATE_IDS):
                    editor.select(GATE_IDS[row])
        elif event == cv2.EVENT_RBUTTONDOWN:
            editor.undo_point()

    cv2.setMouseCallback(window, on_mouse)
    try:
        while True:
            warnings = gate_warnings(editor, scene)
            status = (f"{scene.scene_id} | {video_path.name} | frame {index} ({index / reader.fps:.1f} s) | "
                      f"counting point: {scene.counting_point} | model: {scene.model_id}")
            cv2.imshow(window, render(editor, frame, scale, status, cursor, show_regions, warnings))
            code = cv2.waitKey(30)
            if code == -1:
                if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                    break
                continue
            code &= 0xFF
            if code != ord("q"):
                quit_armed = False
            step = {ord(","): -1, ord("."): 1, ord("["): -round(reader.fps), ord("]"): round(reader.fps),
                    ord("{"): -10 * round(reader.fps), ord("}"): 10 * round(reader.fps)}.get(code)
            if step is not None:
                index, frame = reader.get(index + step)
            elif code == KEY_ESC:
                editor.cancel_points()
            elif code == ord("n") or code == 9:  # Tab
                editor.step(1)
            elif code == ord("p"):
                editor.step(-1)
            elif code == ord("u"):
                editor.undo_point()
            elif code == ord("r"):
                editor.redo()
            elif code == ord("x"):
                editor.delete()
            elif code == ord("t"):
                show_regions = not show_regions
            elif code == ord("s"):
                new_scene = editor.build_scene(scene, index)
                save_scene(new_scene, scene_path)
                scene = new_scene
                editor.dirty = False
                if preview_path is not None:
                    preview = frame.copy()
                    draw_gates(preview, scene, 1.0, show_regions=True)
                    preview_path.parent.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(preview_path), preview, [cv2.IMWRITE_JPEG_QUALITY, 92])
                all_warnings = scene.warnings()
                editor.message = (f"Saved {len(scene.gates)}/12 gates to {scene_path.name}"
                                  + (f"; {len(all_warnings)} warning(s), see terminal" if all_warnings else ""))
                print(f"saved {scene_path} ({len(scene.gates)}/12 gates)", flush=True)
                for warning in all_warnings:
                    print(f"  WARNING {warning}", flush=True)
            elif code == ord("q"):
                if editor.dirty and not quit_armed:
                    editor.message = "Unsaved changes: press q again to quit without saving, s to save"
                    quit_armed = True
                    continue
                break
    finally:
        reader.close()
        cv2.destroyWindow(window)


def default_scene(scene_id: str, video: str, frame_size: tuple[int, int]) -> SceneConfig:
    return SceneConfig(
        scene_id=scene_id,
        video=video,
        frame_size=frame_size,
        view="top_down",
        counting_point="center",
        model_id="yolo11s_visdrone",
        drive_side="right",
    )


__all__ = ["ARMS", "GateEditor", "default_scene", "draw_gates", "run_draw_gates"]
