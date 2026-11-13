"""Contract A model and the vision observation builder."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from backend.models.observation import TrafficObservation
from backend.vision.config import ApproachConfig, CameraConfig
from backend.vision.counting import LineCrossingCounter, TrackedBox
from backend.vision.observation import build_observation, counting_lines, observation_json


def documented_example() -> dict:
    return {
        "schema_version": "1.0",
        "intersection_id": "J1",
        "camera_id": "JamCams_00001.04503",
        "observed_at": "2026-11-13T13:00:10Z",
        "window_duration_s": 10.0,
        "visible_approaches": ["southbound_in", "eastbound_in"],
        "vehicle_counts_by_approach": {
            "southbound_in": {"car": 12, "bus": 1, "bicycle": 2, "total": 15},
            "eastbound_in": {"car": 0, "total": 0},
        },
        "emergency_detections": [
            {
                "tracking_id": "track-847",
                "approach": "southbound_in",
                "vehicle_type": "ambulance",
                "active_lights_detected": True,
                "confidence": 0.91,
            }
        ],
        "source": "recorded_video",
        "model_id": "yolo11-placeholder",
        "confidence": 0.88,
    }


class ContractModelTests(unittest.TestCase):
    def test_documented_example_validates(self) -> None:
        obs = TrafficObservation.model_validate(documented_example())
        self.assertEqual(obs.to_contract_dict()["observed_at"], "2026-11-13T13:00:10Z")

    def test_rejects_negative_counts(self) -> None:
        payload = documented_example()
        payload["vehicle_counts_by_approach"]["southbound_in"]["car"] = -1
        with self.assertRaises(ValidationError):
            TrafficObservation.model_validate(payload)

    def test_rejects_non_integer_counts(self) -> None:
        for bad in (1.5, "3", True):
            payload = documented_example()
            payload["vehicle_counts_by_approach"]["southbound_in"]["car"] = bad
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                TrafficObservation.model_validate(payload)

    def test_rejects_confidence_outside_unit_interval(self) -> None:
        for bad in (-0.01, 1.01):
            payload = documented_example()
            payload["confidence"] = bad
            with self.subTest(top_level=bad), self.assertRaises(ValidationError):
                TrafficObservation.model_validate(payload)
            payload = documented_example()
            payload["emergency_detections"][0]["confidence"] = bad
            with self.subTest(emergency=bad), self.assertRaises(ValidationError):
                TrafficObservation.model_validate(payload)

    def test_null_confidence_allowed(self) -> None:
        payload = documented_example()
        payload["confidence"] = None
        self.assertIsNone(TrafficObservation.model_validate(payload).confidence)

    def test_rejects_counts_for_unlisted_approach(self) -> None:
        payload = documented_example()
        payload["vehicle_counts_by_approach"]["westbound_in"] = {"total": 0}
        with self.assertRaises(ValidationError):
            TrafficObservation.model_validate(payload)

    def test_rejects_non_utc_and_naive_timestamps(self) -> None:
        for bad in ("2026-11-13T15:00:10+02:00", "2026-11-13T13:00:10"):
            payload = documented_example()
            payload["observed_at"] = bad
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                TrafficObservation.model_validate(payload)

    def test_rejects_wrong_version_extra_fields_and_bad_duration(self) -> None:
        for key, value in (("schema_version", "2.0"), ("queue_length", 3), ("window_duration_s", -1.0)):
            payload = documented_example()
            payload[key] = value
            with self.subTest(key=key), self.assertRaises(ValidationError):
                TrafficObservation.model_validate(payload)


CAMERA = CameraConfig(
    intersection_id="J1",
    camera_id="JamCams_00001.04503",
    frame_size=(352, 288),
    approaches=(
        ApproachConfig(approach_id="southbound_in", line=((50, 100), (150, 100)), inbound_point=(100, 130)),
        ApproachConfig(approach_id="eastbound_in", line=((200, 50), (200, 150)), inbound_point=(230, 100)),
    ),
)


class ObservationBuilderTests(unittest.TestCase):
    def build(self, crossings: bool):
        counter = LineCrossingCounter(counting_lines(CAMERA))
        if crossings:
            counter.update(0, [TrackedBox(1, "bus", 0.9, (90, 70, 110, 90))])
            counter.update(1, [TrackedBox(1, "bus", 0.7, (90, 100, 110, 120))])
        return build_observation(
            CAMERA,
            observed_at_utc=datetime(2026, 11, 13, 15, 39, 8, tzinfo=UTC),
            window_duration_s=9.6,
            counts=counter.result(),
            model_id="yolo11m.pt+bytetrack",
        )

    def test_serialises_visible_approaches_only_with_all_class_keys(self) -> None:
        payload = observation_json(self.build(crossings=True))
        self.assertEqual(payload["visible_approaches"], ["southbound_in", "eastbound_in"])
        self.assertEqual(set(payload["vehicle_counts_by_approach"]), {"southbound_in", "eastbound_in"})
        self.assertNotIn("westbound_in", json.dumps(payload))
        self.assertNotIn("northbound_in", json.dumps(payload))
        self.assertEqual(
            payload["vehicle_counts_by_approach"]["southbound_in"],
            {"car": 0, "motorcycle": 0, "bus": 1, "truck": 0, "bicycle": 0, "total": 1},
        )
        self.assertEqual(payload["vehicle_counts_by_approach"]["eastbound_in"]["total"], 0)
        self.assertNotIn("emergency_detections", payload)
        self.assertEqual(payload["source"], "recorded_video")
        self.assertEqual(payload["observed_at"], "2026-11-13T15:39:08Z")
        self.assertAlmostEqual(payload["confidence"], 0.8)

    def test_confidence_null_when_nothing_counted(self) -> None:
        payload = observation_json(self.build(crossings=False))
        self.assertIn("confidence", payload)
        self.assertIsNone(payload["confidence"])
        self.assertEqual(payload["vehicle_counts_by_approach"]["southbound_in"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
