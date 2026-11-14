"""Focused cumulative waiting-time metric tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.simulation.metrics import RunMetrics


class Vehicles:
    def __init__(self) -> None:
        self.waiting: dict[str, float] = {}

    def getWaitingTime(self, vehicle_id: str) -> float:
        return self.waiting[vehicle_id]


class Simulation:
    departed = 0
    arrived = 0

    def getDepartedNumber(self) -> int:
        return self.departed

    def getArrivedNumber(self) -> int:
        return self.arrived


class RunMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vehicles = Vehicles()
        self.simulation = Simulation()
        self.connection = SimpleNamespace(
            vehicle=self.vehicles, simulation=self.simulation
        )
        self.metrics = RunMetrics()

    def record(
        self,
        waiting: dict[str, float],
        *,
        duration: float = 1.0,
        departed: int = 0,
        arrived: int = 0,
        queue: int = 0,
    ) -> None:
        self.vehicles.waiting = waiting
        self.simulation.departed = departed
        self.simulation.arrived = arrived
        self.metrics.record_step(
            self.connection,
            step_duration_s=duration,
            vehicle_ids=waiting,
            network_queue_vehicles=queue,
        )

    def test_multiple_waiting_vehicles_and_no_counter_double_count(self) -> None:
        self.record({"a": 1.0, "b": 1.0}, departed=2, queue=2)
        self.record({"a": 2.0, "b": 0.0}, queue=1)
        self.assertEqual(self.metrics.total_waiting_time_s, 3.0)
        self.assertEqual(self.metrics.departed_vehicle_count, 2)
        self.assertEqual(self.metrics.maximum_network_queue_vehicles, 2)

    def test_arrived_vehicle_wait_is_retained_and_average_uses_departures(self) -> None:
        self.record({"a": 1.0, "b": 1.0}, departed=2)
        self.record({"a": 2.0}, arrived=1)
        self.record({"a": 0.0, "c": 1.0}, departed=1)
        snapshot = self.metrics.snapshot(
            active_vehicle_count=2, network_queue_vehicles=1
        )
        self.assertEqual(snapshot["total_waiting_time_s"], 4.0)
        self.assertAlmostEqual(snapshot["average_waiting_time_s"], 4 / 3)
        self.assertEqual(snapshot["arrived_vehicle_count"], 1)
        self.assertEqual(snapshot["active_vehicle_count"], 2)

    def test_fractional_step_and_fresh_run(self) -> None:
        self.assertIsNone(
            self.metrics.snapshot(
                active_vehicle_count=0, network_queue_vehicles=0
            )["average_waiting_time_s"]
        )
        self.record({"a": 0.5, "b": 0.0}, duration=0.5, departed=2)
        self.assertEqual(self.metrics.total_waiting_time_s, 0.5)
        with self.assertRaises(ValueError):
            self.record({}, duration=-1)


if __name__ == "__main__":
    unittest.main()
