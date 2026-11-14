"""Read-only analytics routes backed by the local SQLite store (backend/analytics/db.py).

Like the other GET routes, these are unauthenticated. The database path is read
on every request, so loading the database needs no API restart.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Response, status

from backend.analytics import db

LOAD_HINT = "run python -m backend.analytics.load"

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Analytics database is not available; {LOAD_HINT}",
    )


@router.get("")
def list_analytics() -> list[dict[str, object]]:
    try:
        return db.list_entries()
    except (db.AnalyticsDatabaseMissing, sqlite3.DatabaseError) as exc:
        raise _unavailable(exc) from exc


@router.get("/{entry_id}")
def get_analytics(entry_id: str) -> Response:
    try:
        payload = db.get_payload(entry_id)
    except (db.AnalyticsDatabaseMissing, sqlite3.DatabaseError) as exc:
        raise _unavailable(exc) from exc
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown analytics id '{entry_id}'")
    # The stored text is already JSON; serve it as-is instead of re-encoding it.
    return Response(payload, media_type="application/json", headers={"Cache-Control": "no-store"})
