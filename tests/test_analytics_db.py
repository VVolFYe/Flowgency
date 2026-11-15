"""Local analytics SQLite store and loader, on a temporary database."""

from __future__ import annotations

import json
import io
import shutil
import sqlite3
import sys
import types
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from backend.analytics import db, load

ROOT = Path(__file__).resolve().parents[1]
YOUTUBE = ROOT / "frontend" / "public" / "analytics" / "youtube.json"
SIMULATION = ROOT / "tests" / "fixtures" / "analytics_simulation_fixture.json"


class AnalyticsLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.public = self.directory / "public"
        self.public.mkdir()
        shutil.copy(YOUTUBE, self.public / "youtube.json")
        shutil.copy(SIMULATION, self.public / "sim_fixture.json")
        self.index = self.public / "index.json"
        self.database = self.directory / "nested" / "analytics.sqlite3"
        self.write_index([
            {"id": "sim_fixture", "label": "Simulation fixture", "kind": "simulation", "file": "sim_fixture.json"},
            {"id": "youtube", "label": "YouTube", "kind": "vision", "file": "youtube.json"},
        ])

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_index(self, entries: list[dict[str, str]]) -> None:
        self.index.write_text(json.dumps(entries), encoding="utf-8")

    def run_loader(self) -> int:
        with mock.patch("builtins.print"):
            return load.main(["--db", str(self.database), "--index", str(self.index)])

    def row_count(self) -> int:
        with closing(sqlite3.connect(self.database)) as connection:
            return connection.execute("SELECT COUNT(*) FROM analytics").fetchone()[0]

    def test_loads_both_kinds_and_is_idempotent(self) -> None:
        self.assertEqual(self.run_loader(), 0)
        first = db.list_entries(self.database)
        self.assertEqual(self.run_loader(), 0)
        second = db.list_entries(self.database)

        self.assertEqual(self.row_count(), 2)
        self.assertEqual([row["id"] for row in second], ["sim_fixture", "youtube"])
        self.assertEqual([row["kind"] for row in second], ["simulation", "vision"])
        self.assertEqual({row["schema_version"] for row in second}, {"1.0"})
        self.assertEqual([row["id"] for row in first], [row["id"] for row in second])
        self.assertTrue(all(row["loaded_at"].endswith("Z") for row in second))
        self.assertEqual(db.get_payload("youtube", self.database), YOUTUBE.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(db.get_payload("sim_fixture", self.database))["kind"], "simulation")
        self.assertIsNone(db.get_payload("unknown", self.database))
        with closing(sqlite3.connect(self.database)) as connection:
            source = connection.execute("SELECT source_file FROM analytics WHERE id='youtube'").fetchone()[0]
        self.assertTrue(source.endswith("public/youtube.json"))

    def test_upsert_replaces_changed_payload(self) -> None:
        self.run_loader()
        changed = json.loads(YOUTUBE.read_text(encoding="utf-8"))
        changed["source"]["label"] = "Relabelled"
        (self.public / "youtube.json").write_text(json.dumps(changed), encoding="utf-8")
        self.run_loader()
        self.assertEqual(self.row_count(), 2)
        self.assertEqual(json.loads(db.get_payload("youtube", self.database))["source"]["label"], "Relabelled")

    def test_missing_file_is_skipped_with_warning(self) -> None:
        (self.public / "sim_fixture.json").unlink()
        entries, warnings = load.read_entries(self.index)
        self.assertEqual([entry.entry_id for entry in entries], ["youtube"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("sim_fixture", warnings[0])
        self.assertEqual(self.run_loader(), 0)
        self.assertEqual(self.row_count(), 1)

    def test_invalid_json_or_unknown_kind_fails_without_writing(self) -> None:
        (self.public / "youtube.json").write_text("{not json", encoding="utf-8")
        with mock.patch("sys.stderr"):
            self.assertEqual(self.run_loader(), 1)
        self.assertFalse(self.database.exists())

        shutil.copy(YOUTUBE, self.public / "youtube.json")
        self.write_index([{"id": "x", "label": "X", "kind": "radar", "file": "youtube.json"}])
        with self.assertRaisesRegex(load.LoadError, "unknown kind"):
            load.read_entries(self.index)
        self.write_index([{"id": "x", "label": "X", "kind": "simulation", "file": "youtube.json"}])
        with self.assertRaisesRegex(load.LoadError, "differs from index kind"):
            load.read_entries(self.index)
        self.write_index([{"id": "x", "label": "X", "kind": "vision", "file": "../youtube.json"}])
        with self.assertRaisesRegex(load.LoadError, "bare .json name"):
            load.read_entries(self.index)

    def test_schema_rejects_unknown_kind(self) -> None:
        db.init_db(self.database)
        with closing(sqlite3.connect(self.database)) as connection, self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO analytics (id, label, kind, payload, loaded_at) VALUES ('a', 'A', 'radar', '{}', 'now')"
            )

    def test_db_path_resolution(self) -> None:
        with mock.patch.dict("os.environ", {db.DB_ENV_VAR: "custom/a.sqlite3"}):
            self.assertEqual(db.db_path(), db.REPOSITORY_ROOT / "custom" / "a.sqlite3")
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(db.db_path(), db.REPOSITORY_ROOT / "data" / "analytics.sqlite3")
        self.assertEqual(db.db_path(self.database), self.database)

    def test_reading_a_missing_database_raises_without_creating_it(self) -> None:
        with self.assertRaises(db.AnalyticsDatabaseMissing):
            db.list_entries(self.database)
        self.assertFalse(self.database.exists())


# Placeholder only; nothing here connects to a network.
FAKE_URL = "postgresql://flowgency:not-a-real-password@db.example.invalid:5432/analytics"


def fake_psycopg(failure_message: str) -> types.ModuleType:
    """A stand-in psycopg whose connect() fails with a message echoing the URL, as libpq can."""
    module = types.ModuleType("psycopg")

    class Error(Exception):
        pass

    class OperationalError(Error):
        pass

    def connect(*_: object, **__: object) -> None:
        raise OperationalError(failure_message)

    module.Error, module.OperationalError, module.connect = Error, OperationalError, connect  # type: ignore[attr-defined]
    return module


class DialectTests(unittest.TestCase):
    """Offline: dialect detection, placeholder translation, and that the URL never leaks."""

    def test_detect_dialect(self) -> None:
        for value in (FAKE_URL, "postgres://u:p@h/d", "  PostgreSQL://h/d"):
            self.assertEqual(db.detect_dialect(value), "postgres", value)
        for value in ("data/analytics.sqlite3", "/abs/path.sqlite3", Path("postgresql://x"), "sqlite:///x.db"):
            self.assertEqual(db.detect_dialect(value), "sqlite", value)

    def test_resolve_from_environment(self) -> None:
        with mock.patch.dict("os.environ", {db.DB_ENV_VAR: FAKE_URL}):
            target = db.resolve()
            self.assertEqual((target.dialect, target.path), ("postgres", None))
            with self.assertRaises(ValueError):
                db.db_path()
        self.assertEqual(db.resolve("x.sqlite3"), db.Target("sqlite", path=db.REPOSITORY_ROOT / "x.sqlite3"))

    def test_placeholder_translation(self) -> None:
        self.assertEqual(
            db.to_postgres("SELECT payload FROM runs WHERE scenario_id = ? AND control_mode IN (?, ?)"),
            "SELECT payload FROM runs WHERE scenario_id = %s AND control_mode IN (%s, %s)",
        )
        self.assertEqual(db.to_postgres("SELECT 5 % 2 WHERE a = ?"), "SELECT 5 %% 2 WHERE a = %s")
        self.assertEqual(db.ORDER_COLUMN, {"sqlite": "rowid", "postgres": "seq"})

    def test_url_is_hidden_in_str_and_repr(self) -> None:
        target = db.resolve(FAKE_URL)
        for text in (str(target), repr(target)):
            self.assertNotIn("not-a-real-password", text)

    def test_missing_psycopg_is_unavailable_without_url(self) -> None:
        with mock.patch.dict(sys.modules, {"psycopg": None}), self.assertRaises(db.AnalyticsDatabaseUnavailable) as caught:
            db.list_entries(FAKE_URL)
        self.assertNotIn("not-a-real-password", str(caught.exception))

    def test_connection_failure_hides_url_from_message_and_chain(self) -> None:
        with mock.patch.dict(sys.modules, {"psycopg": fake_psycopg(f"invalid dsn: {FAKE_URL}")}):
            with self.assertRaises(db.AnalyticsDatabaseUnavailable) as caught:
                db.latest_run_payload(FAKE_URL)
            self.assertNotIn("not-a-real-password", str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)
            self.assertTrue(caught.exception.__suppress_context__)

            stderr, stdout = io.StringIO(), io.StringIO()
            with mock.patch("sys.stderr", stderr), mock.patch("sys.stdout", stdout):
                code = load.main(["--db", FAKE_URL, "--index", str(ROOT / "frontend" / "public" / "analytics" / "index.json")])
            self.assertEqual(code, 1)
            self.assertNotIn("not-a-real-password", stderr.getvalue() + stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
