"""Static analytics index (``frontend/public/analytics/index.json``), stdlib only.

Both the simulation and vision exporters register their output here, so the
index only lists files that were actually generated.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

AnalyticsKind = Literal["simulation", "vision"]
KINDS = ("simulation", "vision")


def upsert_index_entry(
    index_path: Path, *, entry_id: str, label: str, kind: AnalyticsKind, file_path: Path
) -> list[dict[str, str]]:
    """Insert or replace one ``{id, label, kind, file}`` entry, keeping order."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if not entry_id or not label:
        raise ValueError("index entries need a non-empty id and label")
    index_path = index_path.resolve()
    file_name = Path(os.path.relpath(file_path.resolve(), index_path.parent)).as_posix()
    entries: list[dict[str, str]] = []
    if index_path.is_file():
        entries = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            raise ValueError(f"{index_path} is not a JSON list")
    entry = {"id": entry_id, "label": label, "kind": kind, "file": file_name}
    for position, existing in enumerate(entries):
        if existing.get("id") == entry_id:
            entries[position] = entry
            break
    else:
        entries.append(entry)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return entries
