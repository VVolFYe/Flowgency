"""Camera configuration: counting lines in pixel coordinates per camera.

``backend/vision/config/cameras.json`` is written by ``cli draw-lines`` and is
the only committed vision configuration. It holds pixel coordinates and
optional, explicitly unverified SUMO edge IDs (``null`` until verified).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .detections import CountingPoint
from .paths import MAPPING_CANDIDATES_JSON

CONFIG_SCHEMA_VERSION = "1.0"
COMPASS = ("north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest")
APPROACH_ID_RE = re.compile(rf"^({'|'.join(COMPASS)})bound_in$")
MIN_LINE_LENGTH_PX = 5.0
MIN_INBOUND_OFFSET_PX = 3.0

Point = tuple[float, float]


class ConfigError(ValueError):
    """Raised when camera configuration is missing or invalid."""


def validate_approach_id(approach_id: str) -> str:
    if not APPROACH_ID_RE.fullmatch(approach_id):
        raise ValueError(
            f"approach_id {approach_id!r} must look like '<compass>bound_in', "
            f"compass one of {', '.join(COMPASS)}"
        )
    return approach_id


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def inbound_offset_px(line: tuple[Point, Point], inbound_point: Point) -> float:
    """Signed-free perpendicular distance of the inbound point from the line."""
    (x1, y1), (x2, y2) = line
    length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    return abs(_cross(line[0], line[1], inbound_point)) / length if length else 0.0


class ApproachConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    approach_id: str
    line: tuple[Point, Point]
    inbound_point: Point
    sumo_edge_id: str | None = None
    notes: str = ""

    @field_validator("approach_id")
    @classmethod
    def _approach_format(cls, value: str) -> str:
        return validate_approach_id(value)

    @model_validator(mode="after")
    def _geometry(self) -> ApproachConfig:
        (x1, y1), (x2, y2) = self.line
        if ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 < MIN_LINE_LENGTH_PX:
            raise ValueError(f"{self.approach_id}: line shorter than {MIN_LINE_LENGTH_PX}px")
        if inbound_offset_px(self.line, self.inbound_point) < MIN_INBOUND_OFFSET_PX:
            raise ValueError(f"{self.approach_id}: inbound_point lies (almost) on the line")
        return self


class CameraConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intersection_id: Annotated[str, Field(min_length=1)]
    camera_id: Annotated[str, Field(min_length=1)]
    frame_size: tuple[Annotated[int, Field(gt=0)], Annotated[int, Field(gt=0)]]
    reference_frame: str | None = None
    # Street-level JamCams count at the box bottom-centre (road contact point).
    counting_point: CountingPoint = "bottom_center"
    approaches: tuple[ApproachConfig, ...] = ()

    @model_validator(mode="after")
    def _approaches_valid(self) -> CameraConfig:
        ids = [a.approach_id for a in self.approaches]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{self.camera_id}: duplicate approach_id")
        width, height = self.frame_size
        for approach in self.approaches:
            for x, y in (*approach.line, approach.inbound_point):
                if not (0 <= x <= width and 0 <= y <= height):
                    raise ValueError(
                        f"{self.camera_id}/{approach.approach_id}: point ({x}, {y}) "
                        f"outside frame {width}x{height}"
                    )
        return self

    @property
    def approach_ids(self) -> list[str]:
        return [a.approach_id for a in self.approaches]


class CamerasConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = CONFIG_SCHEMA_VERSION
    cameras: list[CameraConfig] = []

    @model_validator(mode="after")
    def _unique(self) -> CamerasConfig:
        ids = [c.camera_id for c in self.cameras]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate camera_id in cameras config")
        return self

    def get(self, camera_id: str) -> CameraConfig:
        for camera in self.cameras:
            if camera.camera_id == camera_id:
                return camera
        raise ConfigError(f"camera {camera_id} is not configured; run `cli draw-lines --camera {camera_id}`")

    def upsert(self, camera: CameraConfig) -> None:
        self.cameras = [c for c in self.cameras if c.camera_id != camera.camera_id] + [camera]
        self.cameras.sort(key=lambda c: (c.intersection_id, c.camera_id))


def load_cameras(path: Path, *, missing_ok: bool = False) -> CamerasConfig:
    if not path.exists():
        if missing_ok:
            return CamerasConfig()
        raise ConfigError(f"camera config {path} not found; run `cli draw-lines` first")
    try:
        return CamerasConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ConfigError(f"invalid camera config {path}: {exc}") from exc


def save_cameras(config: CamerasConfig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(config.model_dump(mode="json"), indent=2) + "\n"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load_camera_registry(path: Path = MAPPING_CANDIDATES_JSON) -> dict[str, str]:
    """Map JamCam ID -> intersection ID from the scenario's mapping candidates."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {t["jamcam_id"]: t["intersection_id"] for t in data["targets"]}
