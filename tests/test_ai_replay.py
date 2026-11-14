from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from backend.simulation.replay import ReplayWriter, inspect_replay, snapshot_to_replay_frame
from backend.simulation.ai_adaptive_run import run_adaptive_experiment
from backend.simulation.ai_fixed_run import run_fixed_experiment
from backend.simulation.geometry import get_scenario_geometry


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "backend" / "vision" / "samples" / "youtube_30s"


def snapshot(time_s: float, vehicle_id: str = "ai_north_1") -> dict:
    return {
        "simulation_time_s": time_s,
        "coordinate_system": "synthetic_cartesian_metres",
        "vehicles": [{
            "vehicle_id": vehicle_id,
            "x_m": 10.5 + time_s,
            "y_m": 20.25,
            "angle_deg": 90.0,
            "speed_mps": 8.5,
            "road_id": "south_in",
            "lane_id": "south_in_0",
        }],
        "traffic_light_controllers": {
            "demo_01": {
                "current_phase_index": 0,
                "current_phase_id": "north_south_green",
                "traffic_light_state": "GrGr",
            }
        },
    }


class ReplayExportTests(unittest.TestCase):
    def test_frame_contains_actual_coordinates_lane_and_tls_state(self) -> None:
        frame = snapshot_to_replay_frame(snapshot(12.0), 3)
        self.assertEqual(frame["schema_version"], "1.0")
        self.assertEqual(frame["simulation_time_s"], 12.0)
        self.assertEqual(frame["vehicles"][0]["x_m"], 22.5)
        self.assertEqual(frame["vehicles"][0]["lane_id"], "south_in_0")
        self.assertEqual(frame["vehicles"][0]["edge_id"], "south_in")
        self.assertEqual(frame["traffic_lights"][0]["traffic_light_id"], "demo_01")
        self.assertEqual(frame["traffic_lights"][0]["state"], "GrGr")

    def test_jsonl_is_streamed_ordered_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.jsonl"
            second = Path(temporary) / "second.jsonl"
            for path in (first, second):
                writer = ReplayWriter(path)
                writer.write_snapshot(snapshot(0.0))
                writer.write_snapshot(snapshot(1.0))
                writer.close()
            self.assertEqual(first.read_bytes(), second.read_bytes())
            info = inspect_replay(first)
        self.assertEqual(info["frame_count"], 2)
        self.assertEqual(info["first_simulation_time_s"], 0.0)
        self.assertEqual(info["last_simulation_time_s"], 1.0)
        self.assertEqual(info["vehicle_ids"], ["ai_north_1"])
        self.assertEqual(info["traffic_light_ids"], ["demo_01"])

    def test_duplicate_timestamp_and_existing_output_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "replay.jsonl"
            writer = ReplayWriter(path)
            writer.write_snapshot(snapshot(0.0))
            with self.assertRaisesRegex(ValueError, "increase strictly"):
                writer.write_snapshot(snapshot(0.0))
            writer.close()
            with self.assertRaises(FileExistsError):
                ReplayWriter(path)

    def test_fixed_and_gap_exports_can_prove_identical_vehicle_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = [Path(temporary) / name for name in ("fixed.jsonl", "gap.jsonl")]
            for path in paths:
                writer = ReplayWriter(path)
                writer.write_snapshot(snapshot(0.0, "ai_north_1"))
                writer.write_snapshot(snapshot(1.0, "ai_east_2"))
                writer.close()
            fixed, gap = (inspect_replay(path) for path in paths)
        self.assertEqual(fixed["vehicle_ids"], gap["vehicle_ids"])


@unittest.skipUnless(shutil.which("sumo"), "SUMO is not installed")
class RealReplaySumoTests(unittest.TestCase):
    def test_real_fixed_and_gap_replays_preserve_demand_and_fixed_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            common = {
                "counts_path": SAMPLE / "counts.jsonl",
                "events_path": SAMPLE / "events.jsonl",
                "max_simulation_time_s": 300.0,
                "wall_timeout_s": 30.0,
            }
            baseline = run_fixed_experiment(
                output_directory=root / "fixed-baseline",
                **common,
            )
            fixed_replay_path = root / "fixed.jsonl"
            fixed = run_fixed_experiment(
                output_directory=root / "fixed-replay",
                replay_output_path=fixed_replay_path,
                **common,
            )
            gap_replay_path = root / "gap.jsonl"
            gap = run_adaptive_experiment(
                output_directory=root / "gap-replay",
                replay_output_path=gap_replay_path,
                adaptive_strategy="gap_v1",
                fixed_demand_route=root / "fixed-replay" / "ai_demand.rou.xml",
                **common,
            )
            fixed_info = inspect_replay(fixed_replay_path)
            gap_info = inspect_replay(gap_replay_path)
            bounds = get_scenario_geometry("single_intersection")["bounds"]
            for replay_path in (fixed_replay_path, gap_replay_path):
                for line in replay_path.read_text(encoding="utf-8").splitlines():
                    for vehicle in json.loads(line)["vehicles"]:
                        self.assertGreaterEqual(vehicle["x_m"], bounds["min_x_m"])
                        self.assertLessEqual(vehicle["x_m"], bounds["max_x_m"])
                        self.assertGreaterEqual(vehicle["y_m"], bounds["min_y_m"])
                        self.assertLessEqual(vehicle["y_m"], bounds["max_y_m"])

        self.assertTrue(baseline["validation"]["passed"])
        self.assertTrue(fixed["validation"]["passed"])
        self.assertTrue(gap["validation"]["passed"])
        self.assertEqual(fixed["trip_metrics"], baseline["trip_metrics"])
        self.assertEqual(fixed["vehicles"], baseline["vehicles"])
        self.assertEqual(fixed_info["vehicle_ids"], gap_info["vehicle_ids"])
        self.assertEqual(len(fixed_info["vehicle_ids"]), fixed["vehicles"]["planned"])
        self.assertEqual(fixed_info["traffic_light_ids"], ["demo_01"])
        self.assertEqual(gap_info["traffic_light_ids"], ["demo_01"])
        self.assertEqual(gap["controller_provenance"]["selected_strategy"], "gap_v1")
        self.assertTrue(gap["controller_provenance"]["active_strategy_verified_at_runtime"])
        self.assertEqual(fixed["diagnostics"]["collisions"], 0)
        self.assertEqual(fixed["diagnostics"]["teleports"], 0)
        self.assertEqual(gap["diagnostics"]["collisions"], 0)
        self.assertEqual(gap["diagnostics"]["teleports"], 0)


if __name__ == "__main__":
    unittest.main()
