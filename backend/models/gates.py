"""Strict producer and forward-compatible consumer models for gate JSONL v1.0.

Vision validates emitted records with the strict ``GateEvent`` and
``GateCounts`` models. Offline simulation ingestion uses the corresponding
``*Input`` models so optional future metadata is retained without weakening
validation of known fields.
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
    """One strictly validated event emitted to ``events.jsonl``."""

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
    """Strictly validated producer counts for one configured camera arm."""

    model_config = ConfigDict(extra="forbid")

    vehicles_on_approach: NonNegativeInt
    entered_total: NonNegativeInt
    discharged_total: NonNegativeInt


class GateCounts(BaseModel):
    """One strictly validated cumulative state emitted to ``counts.jsonl``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    t_s: Seconds
    approaches: dict[Arm, ApproachGateCounts]
    in_intersection: NonNegativeInt | None
    model_id: NonEmptyStr

    def to_contract_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# Event names a consumer accepts. ``approach_left`` (a tracked vehicle left the
# monitored approach region, e.g. it stopped being tracked there or turned away)
# comes from newer vision exports. It never creates demand; the strict producer
# ``GateEvent`` above is intentionally unchanged.
ConsumerEventName = Literal[
    "approach_entered",
    "approach_left",
    "intersection_entered",
    "intersection_exited",
]


class GateEventInput(GateEvent):
    """Consumer event model accepting unknown optional future metadata."""

    model_config = ConfigDict(extra="allow")

    event: ConsumerEventName


class ApproachGateCountsInput(ApproachGateCounts):
    """Consumer approach model accepting unknown nested optional metadata."""

    model_config = ConfigDict(extra="allow")


class GateCountsInput(GateCounts):
    """Consumer count model accepting future top-level and nested metadata."""

    model_config = ConfigDict(extra="allow")
    approaches: dict[Arm, ApproachGateCountsInput]
