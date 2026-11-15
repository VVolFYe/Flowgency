"""Recorded simulation runs: payload builder, recorder, runs table, service recording."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any
from unittest import mock

from backend.analytics import db, load, runs
from backend.simulation.service import SimulationService
from tests.test_simulation_service import FakeRunner, ServiceFixture

ROOT = Path(__file__).resolve().parents[1]
YOUTUBE = ROOT / "frontend" / "public" / "analytics" / "youtube.json"
RUN_INFO = {"run_id": "r1", "scenario_id": "london_normal", "control_mode": "fixed_timing", "status": "finished"}
ADAPTIVE_CONFIGURATION = {"network": "london", "traffic_profile": "normal",
                          "controller_mode": "adaptive_network", "emergency_vehicles_enabled": False}


def fake_sample(t_s: float, queue_a: int | None, queue_b: int | None) -> dict[str, Any]:
    return {
        "t_s": t_s, "network_queue_vehicles": None, "active_vehicle_count": 3,
        "departed_cumulative": 4, "arrived_cumulative": 1,
        "queue_by_traffic_light": {"A": queue_a, "B": queue_b},
        "queue_by_approach": {}, "phase_by_traffic_light": {},
    }


def controller_snapshot(t_s: float, phases: dict[str, tuple[int, str]], *, queue: int = 2) -> dict[str, Any]:
    return {
        "scenario_id": "legacy", "run_id": "ignored", "simulation_time_s": t_s,
        "traffic_light_controllers": {
            tls_id: {"current_phase_index": index, "current_phase_id": f"p{index}",
                     "traffic_light_state": state, "total_queue_vehicles": queue}
            for tls_id, (index, state) in phases.items()
        },
        "queue_lengths_by_approach": {"north": {"vehicles": 1, "measurement": "sumo_halting_number"}},
        "network_queue": {"vehicles": queue},
        "metrics": {"active_vehicle_count": 5, "departed_vehicle_count": 7, "arrived_vehicle_count": 2,
                    "total_time_loss_s": None, "average_waiting_time_s": None},
        "vehicles": [],
    }


class PayloadBuilderTests(unittest.TestCase):
    def test_build_payload_from_fake_samples(self) -> None:
        samples = [fake_sample(5.0, 2, None), fake_sample(10.0, 6, None), fake_sample(15.0, None, None)]
        summary = {"total_time_loss_s": None, "average_waiting_time_s": 1.5}
        payload = runs.build_payload(run=RUN_INFO, summary=summary, samples=samples, phases=[])

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["run"], RUN_INFO)
        self.assertEqual(payload["summary"], summary)
        self.assertIsNone(payload["summary"]["total_time_loss_s"])  # null semantics preserved
        self.assertEqual(payload["timeseries"]["interval_s"], 5.0)
        self.assertEqual(len(payload["timeseries"]["samples"]), 3)
        self.assertEqual(payload["intersections"], [
            {"traffic_light_id": "A", "mean_queue_vehicles": 4.0, "max_queue_vehicles": 6, "sample_count": 2},
            {"traffic_light_id": "B", "mean_queue_vehicles": None, "max_queue_vehicles": None, "sample_count": 0},
        ])
        json.dumps(payload, allow_nan=False)

    def test_empty_samples_and_missing_summary(self) -> None:
        payload = runs.build_payload(run=RUN_INFO, summary=None, samples=[], phases=[])
        self.assertIsNone(payload["summary"])
        self.assertEqual(payload["timeseries"]["samples"], [])
        self.assertEqual(payload["intersections"], [])

    def test_green_state_definition(self) -> None:
        self.assertTrue(runs.is_green_state("GGrr"))
        self.assertTrue(runs.is_green_state("grgr"))
        self.assertFalse(runs.is_green_state("yyrr"))
        self.assertFalse(runs.is_green_state("Gyrr"))
        self.assertFalse(runs.is_green_state("rrrr"))
        self.assertIsNone(runs.is_green_state(None))


class RunRecorderTests(unittest.TestCase):
    def recorder(self, first: dict[str, Any]) -> runs.RunRecorder:
        return runs.RunRecorder(run_id="r1", scenario_id="london_normal", configuration=ADAPTIVE_CONFIGURATION,
                                initial_snapshot=first, started_at="2026-11-14T10:00:00.000Z")

    def test_samples_every_five_simulation_seconds(self) -> None:
        recorder = self.recorder(controller_snapshot(0.0, {"A": (0, "Gr")}))
        for t_s in range(1, 13):
            recorder.observe(controller_snapshot(float(t_s), {"A": (0, "Gr")}))
        payload = recorder.finish("stopped", ended_at="2026-11-14T10:01:00.000Z")
        samples = payload["timeseries"]["samples"]
        self.assertEqual([sample["t_s"] for sample in samples], [5.0, 10.0])
        self.assertEqual(samples[0]["queue_by_traffic_light"], {"A": 2})
        self.assertEqual(samples[0]["queue_by_approach"], {"north": 1})
        self.assertEqual(samples[0]["phase_by_traffic_light"], {"A": {"phase_index": 0, "phase_id": "p0"}})
        self.assertEqual((samples[0]["departed_cumulative"], samples[0]["arrived_cumulative"]), (7, 2))
        self.assertEqual(payload["run"]["sim_duration_s"], 12.0)
        self.assertEqual(payload["run"]["sample_count"], 2)
        self.assertEqual(payload["run"]["legacy_scenario_id"], "legacy")

    def test_large_steps_do_not_backfill_samples(self) -> None:
        recorder = self.recorder(controller_snapshot(0.0, {}))
        recorder.observe(controller_snapshot(12.0, {}))
        recorder.observe(controller_snapshot(14.0, {}))
        recorder.observe(controller_snapshot(15.0, {}))
        self.assertEqual([sample["t_s"] for sample in recorder.samples], [12.0, 15.0])

    def test_run_shorter_than_one_sample_has_empty_timeseries(self) -> None:
        recorder = self.recorder(controller_snapshot(0.0, {"A": (0, "Gr")}))
        recorder.observe(controller_snapshot(3.0, {"A": (0, "Gr")}))
        payload = recorder.finish("finished")
        self.assertEqual(payload["timeseries"]["samples"], [])
        self.assertEqual(payload["intersections"], [])
        self.assertEqual(payload["summary"]["total_time_loss_s"], None)

    def test_phase_changes_and_mean_green(self) -> None:
        # A: green 0-10, yellow 10-13, green 13-20, then still green at the end (excluded).
        timeline = {0: (0, "Gr"), 10: (1, "yr"), 13: (2, "rG"), 20: (0, "Gr")}
        recorder = self.recorder(controller_snapshot(0.0, {"A": timeline[0], "B": (0, "rr")}))
        current = timeline[0]
        for t_s in range(1, 25):
            current = timeline.get(t_s, current)
            recorder.observe(controller_snapshot(float(t_s), {"A": current, "B": (0, "rr")}))
        phases = {item["traffic_light_id"]: item for item in recorder.finish("finished")["phases"]}
        self.assertEqual(phases["A"]["phase_change_count"], 3)
        self.assertEqual(phases["A"]["completed_green_phases"], 2)
        self.assertEqual(phases["A"]["mean_green_duration_s"], 8.5)
        self.assertEqual(phases["B"], {"traffic_light_id": "B", "phase_change_count": 0,
                                       "completed_green_phases": 0, "mean_green_duration_s": None})

    def test_unknown_values_stay_null(self) -> None:
        sample = runs.sample_from_snapshot({"simulation_time_s": 5.0})
        self.assertIsNone(sample["network_queue_vehicles"])
        self.assertIsNone(sample["active_vehicle_count"])
        self.assertIsNone(sample["departed_cumulative"])
        self.assertEqual(sample["queue_by_traffic_light"], {})


class RunsTableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "nested" / "analytics.sqlite3"

    def payload(self, run_id: str, mode: str, ended_at: str, scenario: str = "london_normal") -> dict[str, Any]:
        run = {"run_id": run_id, "scenario_id": scenario, "control_mode": mode, "status": "finished",
               "started_at": "2026-11-14T10:00:00.000Z", "ended_at": ended_at, "sim_duration_s": 20.0}
        return runs.build_payload(run=run, summary=None, samples=[], phases=[])

    def test_save_creates_database_and_reads_latest(self) -> None:
        runs.save_run(self.payload("a", "fixed_timing", "2026-11-14T10:01:00.000Z"), self.database)
        runs.save_run(self.payload("b", "adaptive_network", "2026-11-14T10:03:00.000Z"), self.database)
        runs.save_run(self.payload("c", "fixed_timing", "2026-11-14T10:02:00.000Z", scenario="other"), self.database)
        latest = json.loads(db.latest_run_payload(self.database) or "null")
        self.assertEqual(latest["run"]["run_id"], "b")
        fixed = json.loads(db.latest_run_payload_for("london_normal", db.FIXED_MODES, self.database) or "null")
        self.assertEqual(fixed["run"]["run_id"], "a")
        self.assertIsNone(db.latest_run_payload_for("london_normal", ("adaptive_emergency_priority",), self.database))
        self.assertEqual(db.ADAPTIVE_MODES, ("adaptive_network",))
        self.assertIsNone(db.latest_run_payload_for("london_normal", db.FIXED_MODES, self.database, status="stopped"))
        self.assertIsNotNone(db.latest_run_payload_for("london_normal", db.FIXED_MODES, self.database, status="finished"))
        self.assertEqual(db.list_entries(self.database), [])  # runs are not analytics entries

    def test_status_check_and_duplicate_run_id(self) -> None:
        with self.assertRaises(ValueError):
            db.insert_run(run_id="x", scenario_id="s", control_mode="fixed_timing", status="running",
                          started_at="t", ended_at="t", sim_duration_s=None, payload="{}", path=self.database)
        runs.save_run(self.payload("a", "fixed_timing", "2026-11-14T10:01:00.000Z"), self.database)
        with self.assertRaises(sqlite3.IntegrityError):
            runs.save_run(self.payload("a", "fixed_timing", "2026-11-14T10:02:00.000Z"), self.database)
        with closing(sqlite3.connect(self.database)) as connection, self.assertRaises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO runs VALUES ('y', 's', 'fixed', 'paused', 't', 't', NULL, '{}')")

    def test_loader_never_touches_runs(self) -> None:
        runs.save_run(self.payload("a", "fixed_timing", "2026-11-14T10:01:00.000Z"), self.database)
        public = Path(self.temporary.name) / "public"
        public.mkdir()
        shutil.copy(YOUTUBE, public / "youtube.json")
        index = public / "index.json"
        index.write_text(json.dumps([{"id": "youtube", "label": "YouTube", "kind": "vision", "file": "youtube.json"}]))
        with mock.patch("builtins.print"):
            self.assertEqual(load.main(["--db", str(self.database), "--index", str(index)]), 0)
            self.assertEqual(load.main(["--db", str(self.database), "--index", str(index)]), 0)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT run_id FROM runs").fetchall(), [("a",)])

    def test_reads_never_create_the_file(self) -> None:
        with self.assertRaises(db.AnalyticsDatabaseMissing):
            db.latest_run_payload(self.database)
        self.assertFalse(self.database.exists())


class FailingRunner(FakeRunner):
    def advance(self) -> float:
        super().advance()
        if self.time >= 7.0:
            raise RuntimeError("TraCI connection lost")
        return self.time


class ServiceRecordingTests(unittest.TestCase):
    def make_service(self, sink: Any, runner_class: type[FakeRunner] = FakeRunner) -> SimulationService:
        fixture = ServiceFixture()
        service = SimulationService(
            lambda scenario: runner_class(fixture.operation_threads, fixture.close_events, scenario),
            default_speed=0.1,
            run_sink=sink,
        )
        service.open()
        self.addCleanup(service.shutdown)
        return service

    def wait_for_state(self, service: SimulationService, state: str, timeout_s: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_s
        while service.status()["state"] != state:
            if time.monotonic() > deadline:
                self.fail(f"service did not reach {state}: {service.status()}")
            time.sleep(0.01)

    def test_records_exactly_one_row_on_finish(self) -> None:
        saved: list[dict[str, Any]] = []
        service = self.make_service(saved.append)
        service.start(speed=100.0)
        self.wait_for_state(service, "finished")
        service.stop()  # stopping a finished run must not record it again
        self.assertEqual(len(saved), 1)
        run = saved[0]["run"]
        self.assertEqual((run["status"], run["control_mode"], run["run_id"]), ("finished", "fixed_timing", "fake-run"))
        self.assertEqual(run["scenario_id"], "single_intersection_normal")
        self.assertEqual(
            (run["network"], run["traffic_profile"], run["controller_mode"], run["emergency_vehicles_enabled"]),
            ("single_intersection", "normal", "fixed_timing", False),
        )
        self.assertEqual(run["sim_duration_s"], 20.0)
        self.assertEqual([sample["t_s"] for sample in saved[0]["timeseries"]["samples"]], [5.0, 10.0, 15.0, 20.0])
        self.assertIsNone(saved[0]["summary"])  # the fake snapshot has no metrics: unknown, not zero

    def test_run_identity_uses_configuration_and_emergency_suffix(self) -> None:
        saved: list[dict[str, Any]] = []
        service = self.make_service(saved.append)
        service.start(network="single_intersection", traffic_profile="rush_hour",
                      controller_mode="adaptive_emergency_priority", emergency_vehicles_enabled=True)
        service.stop()
        run = saved[0]["run"]
        self.assertEqual(run["scenario_id"], "single_intersection_rush_hour_emergency")
        self.assertEqual((run["control_mode"], run["controller_mode"]), ("adaptive_emergency_priority",) * 2)
        self.assertEqual((run["traffic_profile"], run["emergency_vehicles_enabled"]), ("rush_hour", True))

    def test_records_exactly_one_row_on_stop(self) -> None:
        saved: list[dict[str, Any]] = []
        service = self.make_service(saved.append)
        service.start()
        self.assertEqual(service.stop()["state"], "idle")
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["run"]["status"], "stopped")
        self.assertEqual(saved[0]["timeseries"]["samples"], [])

    def test_reset_records_the_previous_run_as_stopped(self) -> None:
        saved: list[dict[str, Any]] = []
        service = self.make_service(saved.append)
        service.start()
        service.reset()
        service.stop()
        self.assertEqual([payload["run"]["status"] for payload in saved], ["stopped", "stopped"])

    def test_worker_error_records_error_row(self) -> None:
        saved: list[dict[str, Any]] = []
        service = self.make_service(saved.append, FailingRunner)
        service.start(speed=100.0)
        self.wait_for_state(service, "error")
        service.stop()  # processed after the worker finished recording; stopping does not record again
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["run"]["status"], "error")
        self.assertEqual(saved[0]["run"]["error"], "TraCI connection lost")

    def test_sink_failure_is_logged_and_never_raised(self) -> None:
        def broken_sink(_: dict[str, Any]) -> None:
            raise sqlite3.OperationalError("database is locked")

        service = self.make_service(broken_sink)
        with self.assertLogs("backend.simulation.service", level="ERROR"):
            service.start(speed=100.0)
            self.wait_for_state(service, "finished")
            self.assertIsNone(service.status()["error"])
            self.assertEqual(service.stop()["state"], "idle")  # runs after the failed save
        self.assertEqual(service.start()["state"], "running")
        with self.assertLogs("backend.simulation.service", level="ERROR"):
            service.stop()

    def test_real_database_failure_does_not_raise(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        blocker = Path(temporary.name) / "not-a-directory"
        blocker.write_text("x")
        service = self.make_service(lambda payload: runs.save_run(payload, blocker / "analytics.sqlite3"))
        service.start()
        with self.assertLogs("backend.simulation.service", level="ERROR"):
            self.assertEqual(service.stop()["state"], "idle")

    def test_without_sink_nothing_is_recorded(self) -> None:
        service = self.make_service(None)
        service.start()
        service.stop()
        self.assertIsNone(service._recorder)


if __name__ == "__main__":
    unittest.main()
