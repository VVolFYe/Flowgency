"""Schema v1.0 models for offline gate-count and gate-event JSONL input."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


SCHEMA_VERSION = "1.0"
Arm = Literal["north", "east", "south", "west"]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
Seconds = Annotated[float, Field(ge=0.0)]
NonEmptyStr = Annotated[str, Field(min_length=1)]


class GateEvent(BaseModel):
    """One tracked-vehicle gate trigger from ``events.jsonl``."""

    model_config = ConfigDict(extra="allow")

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    event: Literal["approach_entered", "intersection_entered", "intersection_exited"]
    track_id: NonNegativeInt
    arm: Arm
    origin_arm: Arm | None = None
    t_s: Seconds
    frame: NonNegativeInt
    model_id: NonEmptyStr

    @model_validator(mode="after")
    def validate_origin_arm(self) -> GateEvent:
        origin_was_supplied = "origin_arm" in self.model_fields_set
        if self.event == "intersection_exited" and not origin_was_supplied:
            raise ValueError("intersection_exited requires origin_arm (null when unknown)")
        if self.event != "intersection_exited" and origin_was_supplied:
            raise ValueError(f"{self.event} must not carry origin_arm")
        return self


class ApproachGateCounts(BaseModel):
    """Known count fields for one configured camera arm."""

    model_config = ConfigDict(extra="allow")

    vehicles_on_approach: NonNegativeInt
    entered_total: NonNegativeInt
    discharged_total: NonNegativeInt


class GateCounts(BaseModel):
    """One observed per-second state from ``counts.jsonl``."""

    model_config = ConfigDict(extra="allow")

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    t_s: Seconds
    approaches: dict[Arm, ApproachGateCounts]
    in_intersection: NonNegativeInt | None
    model_id: NonEmptyStr
