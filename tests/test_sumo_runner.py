"""Focused standard-library tests for normalized SUMO state extraction."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.simulation.runner import SumoRunner, load_scenario_mapping

ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = ROOT / "scenarios" / "single_intersection" / "mappings.json"


class FakeSimulation:
    def getTime(self) -> float:
        return 12.0


class FakeTrafficLight:
    def __init__(self) -> None:
        self.duration_requests: list[tuple[str, float]] = []

    def getNextSwitch(self, traffic_light_id: str) -> float:
        return 30.0

    def getPhase(self, traffic_light_id: str) -> int:
        return 0

    def getPhaseName(self, traffic_light_id: str) -> str:
        return "north_south_green"

    def getRedYellowGreenState(self, traffic_light_id: str) -> str:
        return "GrGr"

    def setPhaseDuration(self, traffic_light_id: str, duration: float) -> None:
        self.duration_requests.append((traffic_light_id, duration))


class FakeLane:
    def getLastStepHaltingNumber(self, lane_id: str) -> int:
        return {"south_in_0": 2, "north_in_0": 1}.get(lane_id, 0)


class FakeVehicle:
    def getIDList(self) -> tuple[str, ...]:
        return ("vehicle_b", "vehicle_a")

    def getPosition(self, vehicle_id: str) -> tuple[float, float]:
        return (10.5, 20.25)

    def getTypeID(self, vehicle_id: str) -> str:
        return "passenger"

    def getAngle(self, vehicle_id: str) -> float:
        return 90.0

    def getSpeed(self, vehicle_id: str) -> float:
        return 8.5

    def getRoadID(self, vehicle_id: str) -> str:
        return "south_in"


class RunnerStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = SumoRunner(mapping_path=MAPPING_PATH, run_id="test-run")
        self.runner._connection = SimpleNamespace(
            simulation=FakeSimulation(),
            trafficlight=FakeTrafficLight(),
            lane=FakeLane(),
            vehicle=FakeVehicle(),
        )

    def test_mapping_has_synthetic_verified_ids(self) -> None:
        mapping = load_scenario_mapping(MAPPING_PATH)
        self.assertEqual(mapping["intersection_id"], "demo_01")
        self.assertEqual(mapping["sumo_traffic_light_id"], "demo_01")
        self.assertEqual(len(mapping["controlled_lanes"]), 4)

    def test_snapshot_structure_and_values(self) -> None:
        snapshot = self.runner.extract_snapshot()
        self.assertEqual(snapshot["intersection_id"], "demo_01")
        self.assertEqual(snapshot["traffic_light_id"], "demo_01")
        self.assertEqual(snapshot["current_phase_index"], 0)
        self.assertEqual(snapshot["traffic_light_state"], "GrGr")
        self.assertEqual(snapshot["remaining_phase_duration_s"], 18.0)
        self.assertEqual(snapshot["queue_lengths_by_approach"]["northbound_in"]["vehicles"], 2)
        self.assertTrue(all(q["vehicles"] >= 0 for q in snapshot["queue_lengths_by_approach"].values()))

        vehicles = snapshot["vehicles"]
        self.assertEqual([vehicle["vehicle_id"] for vehicle in vehicles], ["vehicle_a", "vehicle_b"])
        for vehicle in vehicles:
            self.assertIsInstance(vehicle["x_m"], float)
            self.assertIsInstance(vehicle["y_m"], float)
            self.assertIsInstance(vehicle["angle_deg"], float)
            self.assertIsInstance(vehicle["speed_mps"], float)
            self.assertGreaterEqual(vehicle["speed_mps"], 0.0)

    def test_adaptive_adapter_only_adjusts_verified_green_duration(self) -> None:
        connection = self.runner._connection
        self.runner._connection = None
        self.runner.configure_control_mode("adaptive")
        self.runner._connection = connection
        self.runner._apply_adaptive_control()
        self.assertEqual(self.runner.connection.trafficlight.duration_requests, [("demo_01", 2.0)])
        self.assertEqual(self.runner.last_control_reason, "minimum_green_protected")
        self.assertEqual(self.runner.extract_snapshot()["control_reason"], "minimum_green_protected")


if __name__ == "__main__":
    unittest.main()
