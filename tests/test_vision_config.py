"""Camera configuration validation and persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from backend.vision.config import (
    ApproachConfig,
    CameraConfig,
    CamerasConfig,
    ConfigError,
    load_camera_registry,
    load_cameras,
    save_cameras,
    validate_approach_id,
)


def approach(**overrides) -> dict:
    base = {"approach_id": "westbound_in", "line": [[10, 10], [10, 100]], "inbound_point": [0, 50]}
    return {**base, **overrides}


class ConfigTests(unittest.TestCase):
    def test_approach_id_format(self) -> None:
        for ok in ("northbound_in", "southwestbound_in"):
            self.assertEqual(validate_approach_id(ok), ok)
        for bad in ("north_in", "northbound_out", "Northbound_in", "upbound_in", "northbound_in "):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_approach_id(bad)

    def test_rejects_degenerate_geometry(self) -> None:
        with self.assertRaises(ValidationError):
            ApproachConfig.model_validate(approach(line=[[10, 10], [11, 11]]))
        with self.assertRaises(ValidationError):
            ApproachConfig.model_validate(approach(inbound_point=[10, 50]))

    def test_rejects_points_outside_frame_and_duplicates(self) -> None:
        with self.assertRaises(ValidationError):
            CameraConfig.model_validate(
                {"intersection_id": "J1", "camera_id": "c", "frame_size": [50, 50], "approaches": [approach()]}
            )
        with self.assertRaises(ValidationError):
            CameraConfig.model_validate(
                {"intersection_id": "J1", "camera_id": "c", "frame_size": [352, 288],
                 "approaches": [approach(), approach()]}
            )

    def test_round_trip_and_upsert(self) -> None:
        camera = CameraConfig.model_validate(
            {"intersection_id": "J1", "camera_id": "c", "frame_size": [352, 288],
             "reference_frame": "vision_output/reference_frames/c.jpg", "approaches": [approach()]}
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cameras.json"
            self.assertEqual(load_cameras(path, missing_ok=True).cameras, [])
            with self.assertRaises(ConfigError):
                load_cameras(path)
            config = CamerasConfig()
            config.upsert(camera)
            config.upsert(camera)
            save_cameras(config, path)
            loaded = load_cameras(path)
            self.assertEqual(len(loaded.cameras), 1)
            self.assertEqual(loaded.get("c").approaches[0].sumo_edge_id, None)
            with self.assertRaises(ConfigError):
                loaded.get("other")
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_cameras(path)

    def test_registry_from_mapping_candidates(self) -> None:
        registry = load_camera_registry()
        self.assertEqual(registry["JamCams_00001.04503"], "J1")
        self.assertEqual(registry["JamCams_00001.04345"], "J5")
        self.assertEqual(len(registry), 5)


if __name__ == "__main__":
    unittest.main()
