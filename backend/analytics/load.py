"""Load frontend/public/analytics/*.json into the local analytics SQLite database.

    python -m backend.analytics.load [--db PATH] [--index PATH]

Reads index.json, then every listed file, and upserts one row per entry, so it
is safe to run repeatedly. Missing files are skipped with a warning. Invalid JSON,
an unknown kind or a malformed entry fails the whole run before anything is written.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import db

DEFAULT_INDEX = db.REPOSITORY_ROOT / "frontend" / "public" / "analytics" / "index.json"
SAFE_FILE = re.compile(r"^[A-Za-z0-9_.-]+\.json$")


class LoadError(ValueError):
    """The index or a listed file cannot be loaded."""


@dataclass(frozen=True)
class Entry:
    entry_id: str
    label: str
    kind: str
    schema_version: str | None
    payload: str
    source_file: str


def _repository_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(db.REPOSITORY_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _read_json(path: Path) -> tuple[str, object]:
    text = path.read_text(encoding="utf-8")
    try:
        return text, json.loads(text)
    except json.JSONDecodeError as exc:
        raise LoadError(f"{path}: invalid JSON ({exc})") from exc


def read_entries(index_path: Path) -> tuple[list[Entry], list[str]]:
    """Validate the index and its files; return loadable entries and skipped-file warnings."""
    if not index_path.is_file():
        raise LoadError(f"index not found: {index_path}")
    _, index = _read_json(index_path)
    if not isinstance(index, list):
        raise LoadError(f"{index_path}: expected a JSON list")
    entries: list[Entry] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for position, item in enumerate(index):
        where = f"{index_path} entry {position}"
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item.get(key)
                                                 for key in ("id", "label", "kind", "file")):
            raise LoadError(f"{where}: needs non-empty string id, label, kind and file")
        if item["kind"] not in db.KINDS:
            raise LoadError(f"{where}: unknown kind {item['kind']!r} (expected one of {db.KINDS})")
        if not SAFE_FILE.match(item["file"]):
            raise LoadError(f"{where}: file must be a bare .json name, got {item['file']!r}")
        if item["id"] in seen:
            raise LoadError(f"{where}: duplicate id {item['id']!r}")
        seen.add(item["id"])
        path = index_path.parent / item["file"]
        if not path.is_file():
            warnings.append(f"skipped {item['id']}: {_repository_path(path)} is missing")
            continue
        text, payload = _read_json(path)
        if not isinstance(payload, dict):
            raise LoadError(f"{path}: expected a JSON object")
        if payload.get("kind", item["kind"]) != item["kind"]:
            raise LoadError(f"{path}: kind {payload.get('kind')!r} differs from index kind {item['kind']!r}")
        version = payload.get("schema_version")
        entries.append(Entry(
            entry_id=item["id"], label=item["label"], kind=item["kind"],
            schema_version=version if isinstance(version, str) else None,
            payload=text, source_file=_repository_path(path),
        ))
    return entries, warnings


def load(index_path: Path, database: str | Path | None = None) -> tuple[Path, list[Entry], list[str]]:
    entries, warnings = read_entries(index_path)  # validate everything before writing
    path = db.init_db(database)
    for entry in entries:
        db.upsert_entry(
            entry_id=entry.entry_id, label=entry.label, kind=entry.kind,
            schema_version=entry.schema_version, payload=entry.payload,
            source_file=entry.source_file, path=path,
        )
    return path, entries, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", help=f"database path (default ${db.DB_ENV_VAR} or {db.DEFAULT_DB})")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX, help="analytics index.json")
    args = parser.parse_args(argv)
    try:
        path, entries, warnings = load(args.index.resolve(), args.db)
    except (LoadError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"loaded {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} into {path}"
          f" ({len(warnings)} skipped)")
    for entry in entries:
        print(f"  {entry.entry_id} [{entry.kind}] <- {entry.source_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
