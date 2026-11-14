"""Read-only analytics API over the local SQLite store (FastAPI TestClient)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from backend.analytics import db, load, runs
from backend.api.app import create_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "frontend" / "public" / "analytics" / "index.json"
YOUTUBE = ROOT / "frontend" / "public" / "analytics" / "youtube.json"


class StubSimulationService:
    def open(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class AnalyticsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "analytics.sqlite3"
        environment = mock.patch.dict("os.environ", {db.DB_ENV_VAR: str(self.database)})
        environment.start()
        self.addCleanup(environment.stop)
        self.addCleanup(self.temporary.cleanup)
        self.client = TestClient(create_app(service=StubSimulationService()))  # type: ignore[arg-type]

    def load(self) -> None:
        load.load(INDEX)  # database path comes from the patched environment

    def test_list_and_get(self) -> None:
        self.load()
        listing = self.client.get("/api/analytics")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()[0]["id"], "youtube")
        self.assertEqual(set(listing.json()[0]), {"id", "label", "kind", "schema_version", "loaded_at"})

        entry = self.client.get("/api/analytics/youtube")
        self.assertEqual(entry.status_code, 200)
        self.assertEqual(entry.headers["content-type"], "application/json")
        self.assertEqual(entry.json(), json.loads(YOUTUBE.read_text(encoding="utf-8")))

    def test_unknown_id_is_404(self) -> None:
        self.load()
        response = self.client.get("/api/analytics/does_not_exist")
        self.assertEqual(response.status_code, 404)
        self.assertIn("does_not_exist", response.json()["detail"])

    def test_missing_database_is_503_with_loader_hint(self) -> None:
        for path in ("/api/analytics", "/api/analytics/youtube"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 503)
            self.assertIn("run python -m backend.analytics.load", response.json()["detail"])
        self.assertFalse(self.database.exists())  # reads never create the file

    def test_database_without_table_is_503(self) -> None:
        self.database.write_bytes(b"")
        self.assertEqual(self.client.get("/api/analytics").status_code, 503)


    def save_run(self, run_id: str, mode: str, ended_at: str, scenario: str = "london_normal") -> None:
        run = {"run_id": run_id, "scenario_id": scenario, "control_mode": mode, "status": "finished",
               "started_at": "2026-11-14T10:00:00.000Z", "ended_at": ended_at, "sim_duration_s": 60.0}
        runs.save_run(runs.build_payload(run=run, summary={"total_time_loss_s": None}, samples=[], phases=[]))

    def test_latest_run(self) -> None:
        self.save_run("a", "fixed_timing", "2026-11-14T10:01:00.000Z")
        self.save_run("b", "adaptive_network", "2026-11-14T10:05:00.000Z", scenario="other")
        response = self.client.get("/api/analytics/runs/latest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(response.json()["run"]["run_id"], "b")
        self.assertIsNone(response.json()["summary"]["total_time_loss_s"])

    def test_latest_run_is_404_when_none_recorded(self) -> None:
        self.load()  # database exists, runs table empty
        response = self.client.get("/api/analytics/runs/latest")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get("/api/analytics").status_code, 200)

    def test_latest_pair(self) -> None:
        self.save_run("f1", "fixed_timing", "2026-11-14T10:01:00.000Z")
        self.save_run("f2", "fixed_timing", "2026-11-14T10:02:00.000Z")
        self.save_run("e1", "adaptive_emergency_priority", "2026-11-14T10:03:00.000Z")
        self.save_run("x1", "adaptive_network", "2026-11-14T10:09:00.000Z", scenario="other")
        pair = self.client.get("/api/analytics/runs/latest-pair", params={"scenario_id": "london_normal"}).json()
        self.assertEqual(pair["scenario_id"], "london_normal")
        self.assertEqual(pair["fixed"]["run"]["run_id"], "f2")
        self.assertEqual(pair["adaptive"]["run"]["run_id"], "e1")

        only_adaptive = self.client.get("/api/analytics/runs/latest-pair", params={"scenario_id": "other"}).json()
        self.assertIsNone(only_adaptive["fixed"])
        self.assertEqual(only_adaptive["adaptive"]["run"]["run_id"], "x1")
        none = self.client.get("/api/analytics/runs/latest-pair", params={"scenario_id": "unknown"})
        self.assertEqual(none.status_code, 200)
        self.assertEqual(none.json(), {"scenario_id": "unknown", "fixed": None, "adaptive": None})
        self.assertEqual(self.client.get("/api/analytics/runs/latest-pair").status_code, 422)

    def test_runs_missing_database_is_503(self) -> None:
        for path in ("/api/analytics/runs/latest", "/api/analytics/runs/latest-pair?scenario_id=x"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 503)
            self.assertIn("run python -m backend.analytics.load", response.json()["detail"])
        self.assertFalse(self.database.exists())


if __name__ == "__main__":
    unittest.main()
