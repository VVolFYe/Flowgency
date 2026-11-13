"""Focused standard-library tests for normalized SUMO state extraction."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.simulation.runner import SumoRunner, load_scenario_mapping
from backend.controller.adaptive import AdaptiveState

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

    def getIDList(self) -> tuple[str, ...]:
        return ("demo_01",)

    def getControlledLanes(self, traffic_light_id: str) -> tuple[str, ...]:
        return ("south_in_0", "east_in_0", "north_in_0", "west_in_0")

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

    def getLaneID(self, vehicle_id: str) -> str:
        return "south_in_0"


class FakeAmbulance(FakeVehicle):
    def getIDList(self) -> tuple[str, ...]:
        return ("ambulance-1",)

    def getTypeID(self, vehicle_id: str) -> str:
        return "ambulance"

    def getRoadID(self, vehicle_id: str) -> str:
        return "east_in"

    def getLaneID(self, vehicle_id: str) -> str:
        return "east_in_0"


class LateSimulation(FakeSimulation):
    def getTime(self) -> float:
        return 47.0


class EastWestTrafficLight(FakeTrafficLight):
    def getPhase(self, traffic_light_id: str) -> int:
        return 3

    def getPhaseName(self, traffic_light_id: str) -> str:
        return "east_west_green"

    def getRedYellowGreenState(self, traffic_light_id: str) -> str:
        return "rGrG"


class FakeMultiTrafficLight(FakeTrafficLight):
    def getIDList(self) -> tuple[str, ...]:
        return ("tls_b", "tls_a")

    def getControlledLanes(self, traffic_light_id: str) -> tuple[str, ...]:
        return {
            "tls_a": ("south_in_0", "shared_0"),
            "tls_b": ("shared_0", "north_in_0"),
        }[traffic_light_id]

    def getPhaseName(self, traffic_light_id: str) -> str:
        return f"{traffic_light_id}_green"


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
        self.assertEqual(snapshot["scenario_selection_id"], "single_intersection")
        self.assertIn("demo_01", snapshot["traffic_light_controllers"])
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
            self.assertEqual(vehicle["lane_id"], "south_in_0")

    def test_multi_controller_snapshot_deduplicates_network_queue(self) -> None:
        runner = SumoRunner(
            mapping_path=None,
            scenario_selection_id="london_normal",
            legacy_scenario_id="london-oval-kennington-v1",
            coordinate_system="sumo_cartesian_metres_utm_zone_30",
        )
        runner._connection = SimpleNamespace(
            simulation=FakeSimulation(),
            trafficlight=FakeMultiTrafficLight(),
            lane=FakeLane(),
            vehicle=FakeVehicle(),
        )
        snapshot = runner.extract_snapshot()
        self.assertEqual(list(snapshot["traffic_light_controllers"]), ["tls_a", "tls_b"])
        self.assertEqual(snapshot["network_queue"]["controlled_lane_count"], 3)
        self.assertEqual(snapshot["network_queue"]["vehicles"], 3)
        self.assertIsNone(snapshot["traffic_light_id"])
        self.assertEqual(snapshot["queue_lengths_by_approach"], {})

    def test_adaptive_adapter_only_adjusts_verified_green_duration(self) -> None:
        connection = self.runner._connection
        self.runner._connection = None
        self.runner.configure_control_mode("adaptive")
        self.runner._connection = connection
        self.runner._apply_adaptive_control()
        self.assertEqual(self.runner.connection.trafficlight.duration_requests, [("demo_01", 2.0)])
        self.assertEqual(self.runner.last_control_reason, "minimum_green_protected")
        self.assertEqual(self.runner.extract_snapshot()["control_reason"], "minimum_green_protected")

    def test_emergency_mode_holds_green_past_normal_maximum(self) -> None:
        connection = self.runner._connection
        self.runner._connection = None
        self.runner.configure_control_mode("adaptive_with_emergency_priority")
        self.runner._connection = connection
        connection.simulation = LateSimulation()
        connection.trafficlight = EastWestTrafficLight()
        connection.vehicle = FakeAmbulance()
        self.runner._adaptive_state = AdaptiveState(phase_id="east_west_green", phase_started_s=0)

        self.runner._apply_adaptive_control()
        self.assertEqual(connection.trafficlight.duration_requests, [("demo_01", 2.0)])
        snapshot = self.runner.extract_snapshot()
        self.assertTrue(snapshot["vehicles"][0]["is_emergency"])
        self.assertEqual(snapshot["emergency_priority"]["active_vehicle_id"], "ambulance-1")
        self.assertEqual(snapshot["control_reason"], "hold_compatible_green_for_emergency")


if __name__ == "__main__":
    unittest.main()
