"""Scene configuration for gate mode: gates as 4-point pixel polygons.

A scene file (``backend/vision/config/scenes/<scene_id>.json``, separate from
``cameras.json``) is written by ``cli draw-gates``. Arms are named by **image
side** (``north`` = top of the frame, ``south`` = bottom, ``east`` = right,
``west`` = left), not by compass bearing. Each arm has three gates:

* ``<arm>_in.far``: across the inbound lanes at the frame edge;
* ``<arm>_in.stop``: across the inbound lanes just past the stop line;
* ``<arm>_out``: across the outbound lanes just past the crosswalk.

Derived regions (never drawn by hand):

* approach region of an arm = convex hull of its ``in.far`` and ``in.stop`` gates;
* junction region = convex hull of every ``in.stop`` and ``out`` gate, only
  when all eight exist; a point inside an approach region is not in the junction.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .detections import PROFILES, CountingPoint
from .geometry import Point, convex_hull, is_convex, is_simple, point_in_polygon, polygon_area, polygon_width, polygons_overlap

SCENE_SCHEMA_VERSION = "1.0"
ARMS = ("north", "east", "south", "west")
GATE_KINDS = ("in.far", "in.stop", "out")
GATE_IDS = tuple(f"{arm}_{kind}" for arm in ARMS for kind in GATE_KINDS)
GATE_ID_RE = re.compile(r"^(north|east|south|west)_(in\.far|in\.stop|out)$")
MIN_GATE_AREA_PX = 100.0
MIN_GATE_DEPTH_PX = 30.0  # Phase 0: up to ~7 px slow camera drift; keep gates well deeper than that

Quad = tuple[Point, Point, Point, Point]


class SceneError(ValueError):
    """Raised when a scene file is missing or invalid."""


def gate_arm(gate_id: str) -> str:
    return gate_id.split("_", 1)[0]


def gate_kind(gate_id: str) -> str:
    return gate_id.split("_", 1)[1]


def validate_gate_polygon(gate_id: str, polygon: Quad, frame_size: tuple[int, int] | None = None) -> None:
    if not GATE_ID_RE.fullmatch(gate_id):
        raise ValueError(f"unknown gate ID {gate_id!r}; expected one of {', '.join(GATE_IDS)}")
    if len(polygon) != 4:
        raise ValueError(f"{gate_id}: a gate needs exactly 4 points, got {len(polygon)}")
    if not is_simple(polygon):
        raise ValueError(f"{gate_id}: edges cross or points repeat; click the corners in order around the gate")
    if polygon_area(polygon) < MIN_GATE_AREA_PX:
        raise ValueError(f"{gate_id}: area below {MIN_GATE_AREA_PX:.0f} px^2")
    if frame_size is not None:
        width, height = frame_size
        for x, y in polygon:
            if not (0 <= x <= width and 0 <= y <= height):
                raise ValueError(f"{gate_id}: point ({x}, {y}) outside frame {width}x{height}")


class SceneConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = SCENE_SCHEMA_VERSION
    scene_id: Annotated[str, Field(pattern=r"^[a-z0-9_]+$")]
    video: Annotated[str, Field(min_length=1)]  # relative to UNIHACK_DIR, or absolute
    frame_size: tuple[Annotated[int, Field(gt=0)], Annotated[int, Field(gt=0)]]
    view: Literal["top_down", "street"]
    counting_point: CountingPoint
    model_id: str
    drive_side: Literal["right", "left"]
    reference_frame_index: Annotated[int, Field(ge=0)] | None = None
    gates: dict[str, Quad] = {}
    notes: str = ""

    @field_validator("model_id")
    @classmethod
    def _known_model(cls, value: str) -> str:
        if value not in PROFILES:
            raise ValueError(f"unknown model_id {value!r}; known: {', '.join(sorted(PROFILES))}")
        return value

    @model_validator(mode="after")
    def _gates_valid(self) -> SceneConfig:
        for gate_id, polygon in self.gates.items():
            validate_gate_polygon(gate_id, polygon, self.frame_size)
        self.gates = {g: self.gates[g] for g in GATE_IDS if g in self.gates}  # canonical order
        return self

    # --- derived geometry ---------------------------------------------------
    def approach_region(self, arm: str) -> list[Point] | None:
        far, stop = self.gates.get(f"{arm}_in.far"), self.gates.get(f"{arm}_in.stop")
        if far is None or stop is None:
            return None
        return convex_hull([*far, *stop])

    def approach_regions(self) -> dict[str, list[Point]]:
        return {arm: region for arm in ARMS if (region := self.approach_region(arm)) is not None}

    def junction_region(self) -> list[Point] | None:
        needed = [f"{arm}_{kind}" for arm in ARMS for kind in ("in.stop", "out")]
        if any(g not in self.gates for g in needed):
            return None
        return convex_hull([p for g in needed for p in self.gates[g]])

    def locate(self, point: Point) -> str | None:
        """``<arm>`` if in that approach region, ``"junction"`` if in the junction, else ``None``."""
        for arm, region in self.approach_regions().items():
            if point_in_polygon(point, region):
                return arm
        junction = self.junction_region()
        if junction is not None and point_in_polygon(point, junction):
            return "junction"
        return None

    def warnings(self) -> list[str]:
        out = []
        missing = [g for g in GATE_IDS if g not in self.gates]
        if missing:
            out.append(f"missing gates: {', '.join(missing)}")
        ids = list(self.gates)
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                if polygons_overlap(self.gates[a], self.gates[b]):
                    out.append(f"gates overlap: {a} and {b}")
        for gate_id, polygon in self.gates.items():
            depth = polygon_width(polygon)
            if depth < MIN_GATE_DEPTH_PX:
                out.append(f"{gate_id}: only {depth:.0f} px deep (< {MIN_GATE_DEPTH_PX:.0f}); a fast vehicle may "
                           "not stay inside for 2 frames")
            if not is_convex(polygon):
                out.append(f"{gate_id}: not convex; check the corner order")
        regions = self.approach_regions()
        for arm, region in regions.items():
            for other, polygon in self.gates.items():
                if gate_arm(other) != arm and any(point_in_polygon(p, region) for p in polygon):
                    out.append(f"approach region {arm} (hull of its far+stop gates) reaches gate {other}")
        return out


def load_scene(path: Path) -> SceneConfig:
    if not path.exists():
        raise SceneError(f"scene config {path} not found; run `cli draw-gates --scene {path}` first")
    try:
        return SceneConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise SceneError(f"invalid scene config {path}: {exc}") from exc


def scene_json(scene: SceneConfig) -> str:
    """Stable, diff-friendly JSON: one gate per line."""
    data = scene.model_dump(mode="json")
    gates = data.pop("gates")
    head = json.dumps(data, indent=2)[:-2]  # drop closing "\n}"
    lines = [f'    "{g}": {json.dumps(poly, separators=(", ", ": "))}' for g, poly in gates.items()]
    body = ',\n  "gates": {' + ("\n" + ",\n".join(lines) + "\n  }" if lines else "}") + "\n}\n"
    return head + body


def save_scene(scene: SceneConfig, path: Path) -> None:
    SceneConfig.model_validate(json.loads(scene_json(scene)))  # never write something we cannot load
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(scene_json(scene), encoding="utf-8")
    tmp.replace(path)
