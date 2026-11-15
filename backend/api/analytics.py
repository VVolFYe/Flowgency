"""Read-only analytics routes backed by the local SQLite store (backend/analytics/db.py).

Like the other GET routes, these are unauthenticated. The database path is read
on every request, so loading the database needs no API restart. The ``runs``
routes are declared before ``/{entry_id}`` so they can never be shadowed by it.

``POST /insights`` (the Gemini AI review) is the exception: it spends API quota,
so it requires the ``analytics:read`` permission.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from backend.analytics import db
from backend.api.auth import require_permission
from backend.insights.gemini import (
    GeminiInsights,
    InsightsGenerationFailed,
    InsightsNotConfigured,
    api_key_configured,
)
from backend.insights.summary import summarize_latest_runs, summarize_payload

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


class InsightsRequest(BaseModel):
    entry_id: str | None = Field(default=None, min_length=1)


def _run_id(payload: dict[str, Any] | None) -> str | None:
    return (payload.get("run") or {}).get("run_id") if payload else None


def _insights_context(entry_id: str | None) -> tuple[tuple[str | None, ...], dict[str, Any], dict[str, Any]]:
    """``(cache source key, prompt context, response source)`` built from the database only."""
    try:
        if entry_id is None:
            latest_text = db.latest_run_payload()
            if latest_text is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no simulation run recorded yet")
            latest = json.loads(latest_text)
            scenario_id = (latest.get("run") or {}).get("scenario_id")
            fixed_text = adaptive_text = None
            if scenario_id:
                fixed_text = db.latest_run_payload_for(scenario_id, db.FIXED_MODES, status="finished")
                adaptive_text = db.latest_run_payload_for(scenario_id, db.ADAPTIVE_MODES, status="finished")
            fixed = json.loads(fixed_text) if fixed_text is not None else None
            adaptive = json.loads(adaptive_text) if adaptive_text is not None else None
            paired = fixed is not None and adaptive is not None
            key = ("latest_run", _run_id(latest), _run_id(fixed) if paired else None, _run_id(adaptive) if paired else None)
            source = {"kind": "latest_run", "id": _run_id(latest), "scenario_id": scenario_id, "paired": paired}
            return key, summarize_latest_runs(latest, fixed, adaptive), source
        payload_text = db.get_payload(entry_id)
    except db.AnalyticsDatabaseUnavailable as exc:
        raise _unavailable(exc) from exc
    if payload_text is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown analytics id '{entry_id}'")
    try:
        context = summarize_payload(json.loads(payload_text))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ("entry", entry_id), context, {"kind": "entry", "id": entry_id, "scenario_id": None, "paired": False}


@router.post("/insights", dependencies=[Depends(require_permission("analytics:read"))])
def create_insights(body: InsightsRequest, request: Request) -> dict[str, Any]:
    """Gemini review of the latest recorded run (+ its pair) or of one analytics entry.

    The statistics are read from the database here; the client only names the dataset.
    """
    if not api_key_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini is not configured on the backend (set GEMINI_API_KEY)",
        )
    key, context, source = _insights_context(body.entry_id)
    insights: GeminiInsights = request.app.state.insights
    try:
        review, model, cached = insights.review(key, context)
    except InsightsNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except InsightsGenerationFailed as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"source": source, "model": model, "cached": cached, **review.model_dump()}


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
