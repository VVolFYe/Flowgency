"""Pydantic model of contract A (AI traffic observation), schema version 1.0.

Mirrors ``docs/DATA_CONTRACTS.md`` section A. Only the rules stated there are
enforced: counts are non-negative integers, confidences lie in ``[0, 1]``,
timestamps are ISO 8601 UTC, durations are not negative, and only evaluated
(visible) approaches may carry counts. An absent approach means *unknown*,
never zero.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = "1.0"

NonNegativeCount = Annotated[StrictInt, Field(ge=0)]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
NonEmptyStr = Annotated[str, Field(min_length=1)]


class EmergencyDetection(BaseModel):
    """One possible emergency vehicle seen during the observation window."""

    model_config = ConfigDict(extra="forbid")

    tracking_id: NonEmptyStr
    approach: NonEmptyStr
    vehicle_type: NonEmptyStr
    active_lights_detected: bool
    confidence: UnitInterval


class TrafficObservation(BaseModel):
    """Camera evidence for the visible approaches of one intersection and window."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    intersection_id: NonEmptyStr
    camera_id: NonEmptyStr
    observed_at: datetime
    window_duration_s: Annotated[float, Field(gt=0.0)]
    visible_approaches: list[NonEmptyStr]
    vehicle_counts_by_approach: dict[NonEmptyStr, dict[NonEmptyStr, NonNegativeCount]]
    emergency_detections: list[EmergencyDetection] | None = None
    source: NonEmptyStr
    model_id: NonEmptyStr
    confidence: UnitInterval | None = None

    @field_validator("observed_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if offset is None:
            raise ValueError("observed_at must be timezone-aware UTC")
        if offset != timedelta(0):
            raise ValueError("observed_at must be expressed in UTC")
        return value

    @field_validator("visible_approaches")
    @classmethod
    def _unique_approaches(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("visible_approaches must not contain duplicates")
        return value

    @model_validator(mode="after")
    def _counts_only_for_visible(self) -> TrafficObservation:
        visible = set(self.visible_approaches)
        unknown = sorted(set(self.vehicle_counts_by_approach) - visible)
        if unknown:
            raise ValueError(
                f"counts given for approaches not in visible_approaches: {unknown}"
            )
        for detection in self.emergency_detections or ():
            if detection.approach not in visible:
                raise ValueError(
                    f"emergency detection on non-visible approach {detection.approach!r}"
                )
        return self

    def to_contract_dict(self) -> dict[str, Any]:
        """JSON-ready dict; omits ``emergency_detections`` when not evaluated.

        ``confidence`` stays present (possibly ``null``) because it is part of the
        documented payload; an unevaluated emergency list is omitted rather than
        emitted as an empty list, which would claim "none detected".
        """
        exclude = {"emergency_detections"} if self.emergency_detections is None else set()
        return self.model_dump(mode="json", exclude=exclude)
