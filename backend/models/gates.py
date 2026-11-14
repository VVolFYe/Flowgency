"""Pydantic models of the gate-mode vision outputs, schema version 1.0.

Mirrors ``docs/DATA_CONTRACTS.md`` sections I (gate events, ``events.jsonl``)
and J (per-second gate counts, ``counts.jsonl``). Arms are named by image side
of the camera frame (``north`` = top), not by compass bearing. Values are
camera-derived *estimates*; see the contract text for their limits.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

SCHEMA_VERSION = "1.0"

Arm = Literal["north", "east", "south", "west"]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
Seconds = Annotated[float, Field(ge=0.0)]
NonEmptyStr = Annotated[str, Field(min_length=1)]


class GateEvent(BaseModel):
    """One gate trigger by one tracked vehicle (one line of ``events.jsonl``)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    event: Literal["approach_entered", "intersection_entered", "intersection_exited"]
    track_id: NonNegativeInt
    arm: Arm
    # Only on intersection_exited, where it is required and may be null (unknown).
    origin_arm: Arm | None = None
    t_s: Seconds
    frame: NonNegativeInt
    model_id: NonEmptyStr

    @model_validator(mode="after")
    def _origin_only_on_exit(self) -> GateEvent:
        has_origin = "origin_arm" in self.model_fields_set
        if self.event == "intersection_exited" and not has_origin:
            raise ValueError("intersection_exited requires origin_arm (null when unknown)")
        if self.event != "intersection_exited" and has_origin:
            raise ValueError(f"{self.event} must not carry origin_arm")
        return self

    def to_contract_dict(self) -> dict[str, Any]:
        exclude = set() if self.event == "intersection_exited" else {"origin_arm"}
        return self.model_dump(mode="json", exclude=exclude)


class ApproachGateCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicles_on_approach: NonNegativeInt
    entered_total: NonNegativeInt
    discharged_total: NonNegativeInt


class GateCounts(BaseModel):
    """Cumulative state at ``t_s`` (one line of ``counts.jsonl``)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    t_s: Seconds
    approaches: dict[Arm, ApproachGateCounts]
    in_intersection: NonNegativeInt | None
    model_id: NonEmptyStr

    def to_contract_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
