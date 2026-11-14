"""Local SQLite store for analytics (Python stdlib ``sqlite3`` only).

Two independent tables:

- ``analytics``: a derived, regenerable copy of the committed JSON in
  ``frontend/public/analytics/`` (the source of truth), filled by
  ``backend.analytics.load``.
- ``runs``: one row per simulation run started from the UI, written by the
  simulation service (``backend.analytics.runs``). The loader never touches it.
  These rows exist only here: deleting the database file deletes recorded runs.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DB_ENV_VAR = "FLOWGENCY_ANALYTICS_DB"
DEFAULT_DB = Path("data") / "analytics.sqlite3"
KINDS = ("simulation", "vision")
RUN_STATUSES = ("finished", "stopped", "error")
ADAPTIVE_MODES = ("adaptive", "adaptive_with_emergency_priority")

SCHEMA = """
CREATE TABLE IF NOT EXISTS analytics (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('simulation', 'vision')),
    schema_version TEXT,
    payload TEXT NOT NULL,
    source_file TEXT,
    loaded_at TEXT NOT NULL
)
"""

RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    control_mode TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('finished', 'stopped', 'error')),
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    sim_duration_s REAL,
    payload TEXT NOT NULL
)
"""


class AnalyticsDatabaseMissing(RuntimeError):
    """Raised when reading before ``python -m backend.analytics.load`` has run."""


def db_path(path: str | Path | None = None) -> Path:
    """Explicit path, else $FLOWGENCY_ANALYTICS_DB, else data/analytics.sqlite3.

    Relative values resolve against the repository root, not the working directory.
    """
    value = Path(path if path is not None else os.environ.get(DB_ENV_VAR) or DEFAULT_DB)
    return value if value.is_absolute() else REPOSITORY_ROOT / value


def _connect_readonly(path: Path) -> sqlite3.Connection:
    # mode=ro never creates a file, so a missing database stays detectable.
    if not path.is_file():
        raise AnalyticsDatabaseMissing(f"analytics database not found at {path}")
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def init_db(path: str | Path | None = None) -> Path:
    """Create the folder and both tables if missing; return the database path."""
    resolved = db_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(resolved)) as connection, connection:
        connection.execute(SCHEMA)
        connection.execute(RUNS_SCHEMA)
    return resolved


def upsert_entry(
    *, entry_id: str, label: str, kind: str, schema_version: str | None, payload: str,
    source_file: str | None, path: str | Path | None = None, loaded_at: str | None = None,
) -> None:
    """Insert or replace one row; the row keeps its position on update."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    stamp = loaded_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    with closing(sqlite3.connect(db_path(path))) as connection, connection:
        connection.execute(
            """
            INSERT INTO analytics (id, label, kind, schema_version, payload, source_file, loaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                label = excluded.label, kind = excluded.kind,
                schema_version = excluded.schema_version, payload = excluded.payload,
                source_file = excluded.source_file, loaded_at = excluded.loaded_at
            """,
            (entry_id, label, kind, schema_version, payload, source_file, stamp),
        )


def list_entries(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Rows without payloads, in first-loaded order (index.json order)."""
    with closing(_connect_readonly(db_path(path))) as connection:
        rows = connection.execute(
            "SELECT id, label, kind, schema_version, loaded_at FROM analytics ORDER BY rowid"
        ).fetchall()
    return [
        {"id": id_, "label": label, "kind": kind, "schema_version": version, "loaded_at": loaded_at}
        for id_, label, kind, version, loaded_at in rows
    ]


def get_payload(entry_id: str, path: str | Path | None = None) -> str | None:
    """The stored JSON text for ``entry_id``, or ``None`` if the id is unknown."""
    with closing(_connect_readonly(db_path(path))) as connection:
        row = connection.execute("SELECT payload FROM analytics WHERE id = ?", (entry_id,)).fetchone()
    return row[0] if row else None


def insert_run(
    *, run_id: str, scenario_id: str, control_mode: str, status: str, started_at: str,
    ended_at: str, sim_duration_s: float | None, payload: str, path: str | Path | None = None,
) -> None:
    """Insert one recorded run, creating the database if needed. A duplicate run_id raises."""
    if status not in RUN_STATUSES:
        raise ValueError(f"status must be one of {RUN_STATUSES}, got {status!r}")
    resolved = init_db(path)
    with closing(sqlite3.connect(resolved)) as connection, connection:
        connection.execute(
            """
            INSERT INTO runs (run_id, scenario_id, control_mode, status, started_at, ended_at,
                              sim_duration_s, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, scenario_id, control_mode, status, started_at, ended_at, sim_duration_s, payload),
        )


def latest_run_payload(path: str | Path | None = None) -> str | None:
    """Payload of the run with the latest ``ended_at``, or ``None`` if no run is recorded."""
    with closing(_connect_readonly(db_path(path))) as connection:
        row = connection.execute(
            "SELECT payload FROM runs ORDER BY ended_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
    return row[0] if row else None


def latest_run_payload_for(
    scenario_id: str, control_modes: tuple[str, ...], path: str | Path | None = None
) -> str | None:
    """Latest run of ``scenario_id`` whose control_mode is one of ``control_modes``."""
    placeholders = ", ".join("?" for _ in control_modes)
    with closing(_connect_readonly(db_path(path))) as connection:
        row = connection.execute(
            f"SELECT payload FROM runs WHERE scenario_id = ? AND control_mode IN ({placeholders})"
            " ORDER BY ended_at DESC, rowid DESC LIMIT 1",
            (scenario_id, *control_modes),
        ).fetchone()
    return row[0] if row else None
