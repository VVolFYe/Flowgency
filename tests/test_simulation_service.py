"""Lifecycle and API tests with a deterministic in-memory runner double."""

from __future__ import annotations

import asyncio
import threading
import time
import unittest
from typing import Any

import httpx

from backend.api.app import create_app
from backend.simulation.service import InvalidTransition, SimulationService


class FakeRunner:
    def __init__(self, operation_threads: list[str], close_events: list[int]) -> None:
        self.time = 0.0
        self.started = False
        self.closed = False
        self.operation_threads = operation_threads
        self.close_events = close_events

    def _record(self) -> None:
        self.operation_threads.append(threading.current_thread().name)

    def start(self) -> None:
        self._record()
        self.started = True

    def advance(self) -> float:
        self._record()
        self.time += 1.0
        return self.time

    def has_pending_vehicles(self) -> bool:
        self._record()
        return self.time < 20.0

    def extract_snapshot(self) -> dict[str, Any]:
        self._record()
        return {
            "schema_version": "1.0",
            "scenario_id": "single-intersection-v1",
            "run_id": "fake-run",
            "intersection_id": "demo_01",
            "simulation_time_s": self.time,
            "traffic_light_id": "demo_01",
            "current_phase_index": 0,
            "current_phase_id": "north_south_green",
            "remaining_phase_duration_s": 30.0 - self.time,
            "queue_lengths_by_approach": {
                approach: {"vehicles": 0, "measurement": "sumo_halting_number"}
                for approach in (
                    "northbound_in",
                    "southbound_in",
                    "eastbound_in",
                    "westbound_in",
                )
            },
            "traffic_light_state": "GrGr",
            "coordinate_system": "synthetic_cartesian_metres",
            "vehicles": [],
        }

    def close(self) -> None:
        self._record()
        if not self.closed:
            self.close_events.append(1)
            self.closed = True


class ServiceFixture:
    def __init__(self) -> None:
        self.operation_threads: list[str] = []
        self.close_events: list[int] = []

    def factory(self) -> FakeRunner:
        return FakeRunner(self.operation_threads, self.close_events)

    def service(self, speed: float = 0.1) -> SimulationService:
        return SimulationService(self.factory, default_speed=speed)


class SimulationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ServiceFixture()
        self.service = self.fixture.service()
        self.service.open()

    def tearDown(self) -> None:
        self.service.shutdown()

    def test_lifecycle_invalid_operations_and_reset(self) -> None:
        self.assertEqual(self.service.status()["state"], "idle")
        with self.assertRaises(ValueError):
            self.service.start(0)
        with self.assertRaises(InvalidTransition):
            self.service.pause()

        self.assertEqual(self.service.start()["state"], "running")
        with self.assertRaises(InvalidTransition):
            self.service.start()

        self.assertEqual(self.service.pause()["state"], "paused")
        paused_time = self.service.latest_snapshot()["simulation_time_s"]  # type: ignore[index]
        time.sleep(0.02)
        self.assertEqual(
            self.service.latest_snapshot()["simulation_time_s"], paused_time  # type: ignore[index]
        )
        self.assertEqual(self.service.resume()["state"], "running")

        reset_status = self.service.reset()
        self.assertEqual(reset_status["state"], "paused")
        self.assertEqual(reset_status["simulation_time_s"], 0.0)
        self.assertEqual(self.service.stop()["state"], "idle")
        self.assertIsNone(self.service.latest_snapshot())
        with self.assertRaises(InvalidTransition):
            self.service.stop()

        self.assertTrue(self.fixture.operation_threads)
        self.assertEqual(set(self.fixture.operation_threads), {"flowgency-sumo-worker"})

    def test_shutdown_closes_running_runner(self) -> None:
        self.service.start()
        self.service.shutdown()
        self.assertEqual(len(self.fixture.close_events), 1)
        self.assertEqual(self.service.status()["state"], "idle")

    def test_speed_changes_on_worker_while_running_and_paused(self) -> None:
        self.assertEqual(self.service.start(4.0)["simulation_speed"], 4.0)
        self.assertEqual(self.service.set_speed(16.0)["simulation_speed"], 16.0)
        self.assertEqual(self.service.status()["state"], "running")
        self.assertEqual(self.service.pause()["simulation_speed"], 16.0)
        self.assertEqual(self.service.set_speed(2.0)["simulation_speed"], 2.0)
        self.assertEqual(self.service.resume()["simulation_speed"], 2.0)

    def test_speed_validation_and_invalid_state(self) -> None:
        with self.assertRaises(ValueError):
            self.service.set_speed(0.09)
        with self.assertRaises(InvalidTransition):
            self.service.set_speed(8.0)


class SimulationApiTests(unittest.TestCase):
    @unittest.skip(
        "installed AnyIO test portal hangs under Python 3.14; validate through real Uvicorn"
    )
    def test_http_lifecycle(self) -> None:
        asyncio.run(self._exercise_http_lifecycle())

    async def _exercise_http_lifecycle(self) -> None:
        fixture = ServiceFixture()
        service = fixture.service()
        service.open()
        transport = httpx.ASGITransport(app=create_app(service))
        try:
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                self.assertEqual((await client.get("/api/health")).json(), {"status": "ok"})
                self.assertEqual(
                    (await client.get("/api/simulation/status")).json()["state"], "idle"
                )
                self.assertEqual(
                    (await client.get("/api/simulation/snapshot")).status_code, 404
                )

                started = await client.post(
                    "/api/simulation/start", json={"simulation_speed": 0.1}
                )
                self.assertEqual(started.status_code, 200)
                self.assertEqual(started.json()["state"], "running")
                self.assertEqual(
                    (await client.post("/api/simulation/start")).status_code, 409
                )

                paused = await client.post("/api/simulation/pause")
                self.assertEqual(paused.status_code, 200)
                self.assertEqual(paused.json()["state"], "paused")
                snapshot = (await client.get("/api/simulation/snapshot")).json()
                self.assertEqual(snapshot["intersection_id"], "demo_01")

                reset = await client.post("/api/simulation/reset")
                self.assertEqual(reset.json()["state"], "paused")
                resumed = await client.post(
                    "/api/simulation/resume", json={"simulation_speed": 2.0}
                )
                self.assertEqual(resumed.json()["state"], "running")
                self.assertEqual(resumed.json()["simulation_speed"], 2.0)
                self.assertEqual(
                    (await client.post("/api/simulation/stop")).json()["state"], "idle"
                )
        finally:
            service.shutdown()

        self.assertGreaterEqual(len(fixture.close_events), 2)
        self.assertEqual(set(fixture.operation_threads), {"flowgency-sumo-worker"})


if __name__ == "__main__":
    unittest.main()
