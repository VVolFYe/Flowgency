"""Build and validate contract-A payloads from per-clip counts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.models.observation import TrafficObservation

from .config import CameraConfig
from .counting import CountingLine, CountResult

SOURCE_RECORDED_VIDEO = "recorded_video"


def counting_lines(camera: CameraConfig) -> list[CountingLine]:
    return [
        CountingLine(a.approach_id, tuple(a.line[0]), tuple(a.line[1]), tuple(a.inbound_point))
        for a in camera.approaches
    ]


def build_observation(
    camera: CameraConfig,
    *,
    observed_at_utc: datetime,
    window_duration_s: float,
    counts: CountResult,
    model_id: str,
    source: str = SOURCE_RECORDED_VIDEO,
) -> TrafficObservation:
    """One observation per clip.

    ``visible_approaches`` are exactly the approaches configured for the camera;
    unconfigured approaches are absent (unknown), never zero. Zeros for a
    configured approach are real measurements. ``emergency_detections`` is
    omitted because emergency detection is not evaluated yet.
    """
    visible = camera.approach_ids
    if set(counts.counts_by_approach) != set(visible):
        raise ValueError("count result does not match the camera's configured approaches")
    for approach_id, by_class in counts.counts_by_approach.items():
        if by_class["total"] != sum(v for k, v in by_class.items() if k != "total"):
            raise ValueError(f"{approach_id}: total does not equal the class sum")
    return TrafficObservation(
        intersection_id=camera.intersection_id,
        camera_id=camera.camera_id,
        observed_at=observed_at_utc,
        window_duration_s=window_duration_s,
        visible_approaches=visible,
        vehicle_counts_by_approach={a: dict(counts.counts_by_approach[a]) for a in visible},
        source=source,
        model_id=model_id,
        confidence=counts.confidence,
    )


def observation_json(observation: TrafficObservation) -> dict[str, Any]:
    # Round-trip through the model so every emitted payload is validated.
    payload = observation.to_contract_dict()
    TrafficObservation.model_validate(payload)
    return payload
