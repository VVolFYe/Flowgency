"""Read-only analytics API over the local SQLite store (FastAPI TestClient)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from backend.analytics import db, load
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


if __name__ == "__main__":
    unittest.main()
