"""Analytics store: a local SQLite file (default) or the team's hosted Postgres.

``$FLOWGENCY_ANALYTICS_DB`` (or an explicit ``path``) selects the target: a
``postgresql://`` / ``postgres://`` URL uses Postgres through psycopg 3,
anything else is a SQLite path (stdlib ``sqlite3``). The URL holds a password,
so it is never logged, printed or put in an exception message.

Two independent tables:

- ``analytics``: a derived, regenerable copy of the committed JSON in
  ``frontend/public/analytics/`` (the source of truth), filled by
  ``backend.analytics.load``.
- ``runs``: one row per simulation run started from the UI, written by the
  simulation service (``backend.analytics.runs``). The loader never touches it.
  These rows exist only here: deleting the database deletes recorded runs.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DB_ENV_VAR = "FLOWGENCY_ANALYTICS_DB"
DEFAULT_DB = Path("data") / "analytics.sqlite3"
KINDS = ("simulation", "vision")
RUN_STATUSES = ("finished", "stopped", "error")
# Controller modes of SimulationConfiguration (backend/simulation/scenarios.py).
FIXED_MODES = ("fixed_timing",)
ADAPTIVE_MODES = ("adaptive_network", "adaptive_emergency_priority")
POSTGRES_PREFIXES = ("postgresql://", "postgres://")
CONNECT_TIMEOUT_S = 5
# Insertion order: SQLite's implicit rowid, Postgres' identity column ``seq``.
ORDER_COLUMN = {"sqlite": "rowid", "postgres": "seq"}

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

# Same columns and constraints; ``seq`` replaces SQLite's rowid for ordering, and
# DOUBLE PRECISION matches SQLite's 8-byte REAL (Postgres REAL is only 4 bytes).
POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS analytics (
    seq BIGINT GENERATED ALWAYS AS IDENTITY,
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('simulation', 'vision')),
    schema_version TEXT,
    payload TEXT NOT NULL,
    source_file TEXT,
    loaded_at TEXT NOT NULL
)
"""

POSTGRES_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    seq BIGINT GENERATED ALWAYS AS IDENTITY,
    run_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    control_mode TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('finished', 'stopped', 'error')),
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    sim_duration_s DOUBLE PRECISION,
    payload TEXT NOT NULL
)
"""


class AnalyticsDatabaseUnavailable(RuntimeError):
    """The database cannot be read: missing file, missing table, or failed connection.

    Messages never contain the Postgres URL.
    """


class AnalyticsDatabaseMissing(AnalyticsDatabaseUnavailable):
    """The SQLite file does not exist yet (before the loader or the first recorded run)."""


Dialect = Literal["sqlite", "postgres"]


@dataclass(frozen=True)
class Target:
    """A resolved database. ``str()`` and ``repr()`` never include the Postgres URL."""

    dialect: Dialect
    path: Path | None = None
    url: str | None = field(default=None, repr=False)

    def __str__(self) -> str:
        return str(self.path) if self.dialect == "sqlite" else "hosted Postgres (URL hidden)"


def detect_dialect(value: str | Path) -> Dialect:
    """``postgres`` for a postgresql:// or postgres:// URL, else ``sqlite``."""
    if isinstance(value, str) and value.strip().lower().startswith(POSTGRES_PREFIXES):
        return "postgres"
    return "sqlite"


def resolve(path: str | Path | Target | None = None) -> Target:
    """Explicit value, else $FLOWGENCY_ANALYTICS_DB, else data/analytics.sqlite3.

    Relative SQLite paths resolve against the repository root, not the working directory.
    """
    if isinstance(path, Target):
        return path
    value: str | Path = path if path is not None else os.environ.get(DB_ENV_VAR) or DEFAULT_DB
    if detect_dialect(value) == "postgres":
        return Target("postgres", url=str(value).strip())
    resolved = Path(value)
    return Target("sqlite", path=resolved if resolved.is_absolute() else REPOSITORY_ROOT / resolved)


def db_path(path: str | Path | None = None) -> Path:
    """The SQLite file path (see :func:`resolve`); a Postgres URL raises ``ValueError``."""
    target = resolve(path)
    if target.path is None:
        raise ValueError(f"{DB_ENV_VAR} is a Postgres URL, not a file path")
    return target.path


def to_postgres(sql: str) -> str:
    """Translate qmark placeholders to psycopg's ``%s`` (a literal ``%`` becomes ``%%``).

    The SQL in this module never contains ``?`` or ``%`` inside string literals.
    """
    return sql.replace("%", "%%").replace("?", "%s")


def _execute(connection: Any, target: Target, sql: str, params: tuple[Any, ...] = ()) -> Any:
    """Run one statement on either dialect and return the cursor."""
    return connection.execute(to_postgres(sql) if target.dialect == "postgres" else sql, params)


def _psycopg() -> Any:
    try:
        import psycopg
    except ModuleNotFoundError:
        raise AnalyticsDatabaseUnavailable(
            f"{DB_ENV_VAR} is a Postgres URL but psycopg is not installed "
            "(pip install -r backend/requirements.txt)"
        ) from None
    return psycopg


@contextmanager
def _connect(target: Target, *, readonly: bool = False) -> Iterator[Any]:
    """One new connection per call; commits on success, rolls back on error, always closes."""
    if target.dialect == "sqlite":
        assert target.path is not None
        if readonly:
            # mode=ro never creates a file, so a missing database stays detectable.
            if not target.path.is_file():
                raise AnalyticsDatabaseMissing(f"analytics database not found at {target.path}")
            connection = sqlite3.connect(f"{target.path.as_uri()}?mode=ro", uri=True)
        else:
            connection = sqlite3.connect(target.path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()
        return

    psycopg = _psycopg()
    try:
        connection = psycopg.connect(target.url, connect_timeout=CONNECT_TIMEOUT_S)
    except psycopg.Error as exc:
        # ``from None``: libpq messages can echo parts of the connection string.
        raise AnalyticsDatabaseUnavailable(
            f"cannot connect to the hosted analytics database ({type(exc).__name__})"
        ) from None
    try:
        if readonly:
            connection.read_only = True
        with connection:  # psycopg 3: commit or roll back, then close
            yield connection
    finally:
        connection.close()


def _is_unavailable(target: Target, exc: BaseException) -> bool:
    if target.dialect == "sqlite":
        return isinstance(exc, sqlite3.DatabaseError)  # e.g. no such table, not a database
    psycopg = _psycopg()
    return isinstance(exc, (psycopg.OperationalError, psycopg.errors.UndefinedTable))


def _read(path: str | Path | Target | None, sql: str, params: tuple[Any, ...] = (), *, many: bool) -> Any:
    """Read-only query; storage failures become :class:`AnalyticsDatabaseUnavailable`.

    ``{order}`` in ``sql`` becomes the dialect's insertion-order column.
    """
    target = resolve(path)
    sql = sql.replace("{order}", ORDER_COLUMN[target.dialect])
    try:
        with _connect(target, readonly=True) as connection:
            cursor = _execute(connection, target, sql, params)
            return cursor.fetchall() if many else cursor.fetchone()
    except AnalyticsDatabaseUnavailable:
        raise
    except Exception as exc:
        if not _is_unavailable(target, exc):
            raise
        message = f"analytics database is not readable ({type(exc).__name__})"
        if target.dialect == "postgres":
            raise AnalyticsDatabaseUnavailable(message) from None
        raise AnalyticsDatabaseUnavailable(message) from exc


def init_db(path: str | Path | Target | None = None) -> Target:
    """Create both tables if missing (and, for SQLite, the folder); return the target."""
    target = resolve(path)
    if target.dialect == "sqlite":
        assert target.path is not None
        target.path.parent.mkdir(parents=True, exist_ok=True)
        schemas = (SCHEMA, RUNS_SCHEMA)
    else:
        schemas = (POSTGRES_SCHEMA, POSTGRES_RUNS_SCHEMA)
    with _connect(target) as connection:
        for schema in schemas:
            _execute(connection, target, schema)
    return target


def upsert_entry(
    *, entry_id: str, label: str, kind: str, schema_version: str | None, payload: str,
    source_file: str | None, path: str | Path | Target | None = None, loaded_at: str | None = None,
) -> None:
    """Insert or replace one row; the row keeps its position on update."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    stamp = loaded_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    target = resolve(path)
    with _connect(target) as connection:
        _execute(
            connection, target,
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


def list_entries(path: str | Path | Target | None = None) -> list[dict[str, Any]]:
    """Rows without payloads, in first-loaded order (index.json order)."""
    rows = _read(path, "SELECT id, label, kind, schema_version, loaded_at FROM analytics ORDER BY {order}", many=True)
    return [
        {"id": id_, "label": label, "kind": kind, "schema_version": version, "loaded_at": loaded_at}
        for id_, label, kind, version, loaded_at in rows
    ]


def get_payload(entry_id: str, path: str | Path | Target | None = None) -> str | None:
    """The stored JSON text for ``entry_id``, or ``None`` if the id is unknown."""
    row = _read(path, "SELECT payload FROM analytics WHERE id = ?", (entry_id,), many=False)
    return row[0] if row else None


def insert_run(
    *, run_id: str, scenario_id: str, control_mode: str, status: str, started_at: str,
    ended_at: str, sim_duration_s: float | None, payload: str, path: str | Path | Target | None = None,
) -> None:
    """Insert one recorded run, creating the tables if needed. A duplicate run_id raises."""
    if status not in RUN_STATUSES:
        raise ValueError(f"status must be one of {RUN_STATUSES}, got {status!r}")
    target = init_db(path)
    with _connect(target) as connection:
        _execute(
            connection, target,
            """
            INSERT INTO runs (run_id, scenario_id, control_mode, status, started_at, ended_at,
                              sim_duration_s, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, scenario_id, control_mode, status, started_at, ended_at, sim_duration_s, payload),
        )


def latest_run_payload(path: str | Path | Target | None = None) -> str | None:
    """Payload of the run with the latest ``ended_at``, or ``None`` if no run is recorded."""
    row = _read(path, "SELECT payload FROM runs ORDER BY ended_at DESC, {order} DESC LIMIT 1", many=False)
    return row[0] if row else None


def latest_run_payload_for(
    scenario_id: str, control_modes: tuple[str, ...], path: str | Path | Target | None = None
) -> str | None:
    """Latest run of ``scenario_id`` whose control_mode is one of ``control_modes``."""
    placeholders = ", ".join("?" for _ in control_modes)
    row = _read(
        path,
        f"SELECT payload FROM runs WHERE scenario_id = ? AND control_mode IN ({placeholders})"
        " ORDER BY ended_at DESC, {order} DESC LIMIT 1",
        (scenario_id, *control_modes),
        many=False,
    )
    return row[0] if row else None
