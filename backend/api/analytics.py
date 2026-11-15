"""Read-only analytics routes backed by the local SQLite store (backend/analytics/db.py).

Like the other GET routes, these are unauthenticated. The database path is read
on every request, so loading the database needs no API restart. The ``runs``
routes are declared before ``/{entry_id}`` so they can never be shadowed by it.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Response, status

from backend.analytics import db

LOAD_HINT = "run python -m backend.analytics.load"

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Analytics database is not available; check FLOWGENCY_ANALYTICS_DB (unset = local SQLite) and {LOAD_HINT}",
    )


@router.get("")
def list_analytics() -> list[dict[str, object]]:
    try:
        return db.list_entries()
    except db.AnalyticsDatabaseUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/runs/latest")
def get_latest_run() -> Response:
    try:
        payload = db.latest_run_payload()
    except db.AnalyticsDatabaseUnavailable as exc:
        raise _unavailable(exc) from exc
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no simulation run recorded yet")
    return Response(payload, media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/runs/latest-pair")
def get_latest_run_pair(scenario_id: str = Query(min_length=1)) -> Response:
    try:
        # Like main's RunComparison: finished runs only, adaptive_network only.
        fixed = db.latest_run_payload_for(scenario_id, db.FIXED_MODES, status="finished")
        adaptive = db.latest_run_payload_for(scenario_id, db.ADAPTIVE_MODES, status="finished")
    except db.AnalyticsDatabaseUnavailable as exc:
        raise _unavailable(exc) from exc
    body = {
        "scenario_id": scenario_id,
        "fixed": json.loads(fixed) if fixed is not None else None,
        "adaptive": json.loads(adaptive) if adaptive is not None else None,
    }
    return Response(json.dumps(body), media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/{entry_id}")
def get_analytics(entry_id: str) -> Response:
    try:
        payload = db.get_payload(entry_id)
    except db.AnalyticsDatabaseUnavailable as exc:
        raise _unavailable(exc) from exc
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown analytics id '{entry_id}'")
    # The stored text is already JSON; serve it as-is instead of re-encoding it.
    return Response(payload, media_type="application/json", headers={"Cache-Control": "no-store"})
