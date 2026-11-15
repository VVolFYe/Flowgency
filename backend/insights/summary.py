"""Compact summaries of analytics payloads for the AI review prompt.

Pure functions over the documents of DATA_CONTRACTS.md O.2, O.3 and O.5. Large
arrays (per-sample time series, histograms, per-controller tables) are reduced
to summary statistics so the prompt stays small. ``None`` stays ``None``:
unknown values are never turned into zero.
"""

from __future__ import annotations

from typing import Any

TOP_CONTROLLERS = 5


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def series_stats(values: list[Any]) -> dict[str, Any]:
    """``{samples, known, min, mean, max, last}`` over the known numeric values."""
    known = [number for number in map(_number, values) if number is not None]
    if not known:
        return {"samples": len(values), "known": 0, "min": None, "mean": None, "max": None, "last": None}
    return {
        "samples": len(values),
        "known": len(known),
        "min": _round(min(known)),
        "mean": _round(sum(known) / len(known)),
        "max": _round(max(known)),
        "last": _round(known[-1]),
    }


def _top(rows: list[dict[str, Any]], key: str, limit: int = TOP_CONTROLLERS) -> list[dict[str, Any]]:
    """Rows with a known ``key``, highest first; unknown rows are left out (and counted by the caller)."""
    known = [row for row in rows if _number(row.get(key)) is not None]
    return sorted(known, key=lambda row: _number(row[key]) or 0.0, reverse=True)[:limit]


def _records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def summarize_simulation_comparison(payload: dict[str, Any]) -> dict[str, Any]:
    """O.2 fixed vs adaptive document."""
    timeseries = payload.get("timeseries") or {}
    series: dict[str, Any] = {}
    for mode in ("fixed", "adaptive"):
        samples = _records(timeseries.get(mode))
        series[mode] = {
            field: series_stats([sample.get(field) for sample in samples])
            for field in ("network_queue_vehicles", "active_vehicles", "arrived_cumulative")
        }

    distributions = {
        metric: {
            mode: {k: v for k, v in (body.get(mode) or {}).items() if k != "histogram"}
            for mode in ("fixed", "adaptive")
        }
        for metric, body in (payload.get("distributions") or {}).items()
        if isinstance(body, dict)
    }

    intersections_in = payload.get("intersections") or {}
    intersections: dict[str, Any] = {"queue_measurement": intersections_in.get("queue_measurement")}
    for mode in ("fixed", "adaptive"):
        by_id = intersections_in.get(mode) or {}
        rows = [{"traffic_light_id": tl_id, **values} for tl_id, values in by_id.items() if isinstance(values, dict)]
        intersections[mode] = {
            "controller_count": len(rows),
            "total_decision_count": sum(int(_number(row.get("decision_count")) or 0) for row in rows),
            f"top_{TOP_CONTROLLERS}_by_mean_queue": _top(rows, "mean_queue"),
        }

    validation = payload.get("validation") or {}
    return {
        "kind": "simulation_fixed_vs_adaptive",
        "scenario_id": payload.get("scenario_id"),
        "scenario_name": payload.get("scenario_name"),
        "experiment": payload.get("experiment"),
        "runs": payload.get("runs"),
        "summary": payload.get("summary"),
        "timeseries_interval_s": timeseries.get("interval_s"),
        "queue_measurement": timeseries.get("queue_measurement"),
        "timeseries_stats": series,
        "distributions": distributions,
        "intersections": intersections,
        "emergency": payload.get("emergency"),
        "validation": {
            "passed": validation.get("passed"),
            "matched_vehicle_count": validation.get("matched_vehicle_count"),
            "errors": validation.get("errors"),
            **{mode: validation.get(mode) for mode in ("fixed", "adaptive")},
        },
        "limitations": payload.get("limitations"),
    }


def summarize_vision(payload: dict[str, Any]) -> dict[str, Any]:
    """O.3 vision gate-count document."""
    source = payload.get("source") or {}
    timeseries = payload.get("timeseries") or {}
    approach = timeseries.get("vehicles_on_approach") or {}
    windows = _records(payload.get("flow_per_minute"))
    arms = [arm for arm in payload.get("arms") or [] if isinstance(arm, str)]
    flow = {
        arm: {
            "entered_per_minute": series_stats([(w.get("entered") or {}).get(arm) for w in windows]),
            "discharged_per_minute": series_stats([(w.get("discharged") or {}).get(arm) for w in windows]),
        }
        for arm in arms
    }
    return {
        "kind": "vision_gate_counts",
        "source": {k: source.get(k) for k in ("label", "duration_s", "fps", "model_id")},
        "arms": arms,
        "vehicles_on_approach_stats": {
            arm: series_stats(values) for arm, values in approach.items() if isinstance(values, list)
        },
        "in_intersection_stats": series_stats(timeseries.get("in_intersection") or []),
        "flow_minutes": len(windows),
        "partial_minutes": sum(1 for w in windows if w.get("partial")),
        "flow_per_minute_stats": flow,
        "totals": payload.get("totals"),
        "turning_matrix": payload.get("turning_matrix"),
        "limitations": payload.get("limitations"),
    }


def summarize_recorded_run(payload: dict[str, Any]) -> dict[str, Any]:
    """O.5 recorded Live Simulation run."""
    timeseries = payload.get("timeseries") or {}
    samples = _records(timeseries.get("samples"))
    intersections = _records(payload.get("intersections"))
    phases = _records(payload.get("phases"))
    green_means = [n for n in (_number(p.get("mean_green_duration_s")) for p in phases) if n is not None]
    return {
        "kind": "simulation_run",
        "run": payload.get("run"),
        "summary": payload.get("summary"),
        "timeseries_interval_s": timeseries.get("interval_s"),
        "queue_measurement": timeseries.get("queue_measurement"),
        "timeseries_stats": {
            field: series_stats([sample.get(field) for sample in samples])
            for field in ("network_queue_vehicles", "active_vehicle_count", "departed_cumulative", "arrived_cumulative")
        },
        "intersections": {
            "controller_count": len(intersections),
            f"top_{TOP_CONTROLLERS}_by_mean_queue": _top(intersections, "mean_queue_vehicles"),
        },
        "phases": {
            "controller_count": len(phases),
            "total_phase_changes": sum(int(_number(p.get("phase_change_count")) or 0) for p in phases),
            "total_completed_green_phases": sum(int(_number(p.get("completed_green_phases")) or 0) for p in phases),
            "mean_of_mean_green_duration_s": _round(sum(green_means) / len(green_means)) if green_means else None,
            "controllers_with_unknown_green_duration": len(phases) - len(green_means),
        },
    }


def summarize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Dispatch on the document ``kind``; unknown kinds are rejected rather than guessed."""
    kind = payload.get("kind")
    if kind == "simulation":
        return summarize_simulation_comparison(payload)
    if kind == "vision":
        return summarize_vision(payload)
    if kind == "simulation_run":
        return summarize_recorded_run(payload)
    raise ValueError(f"unsupported analytics document kind {kind!r}")


def summarize_latest_runs(
    latest: dict[str, Any], fixed: dict[str, Any] | None, adaptive: dict[str, Any] | None
) -> dict[str, Any]:
    """The latest recorded run plus, when both exist, the finished fixed/adaptive pair of its scenario.

    A pair run that is the latest run itself is referenced instead of repeated.
    """
    latest_id = (latest.get("run") or {}).get("run_id")
    context: dict[str, Any] = {"latest_run": summarize_recorded_run(latest)}
    if fixed is not None and adaptive is not None:
        pair: dict[str, Any] = {}
        for mode, run in (("fixed", fixed), ("adaptive", adaptive)):
            run_id = (run.get("run") or {}).get("run_id")
            pair[mode] = {"same_as": "latest_run", "run_id": run_id} if run_id == latest_id else summarize_recorded_run(run)
        context["fixed_vs_adaptive_live_runs"] = pair
    else:
        context["fixed_vs_adaptive_live_runs"] = None
        context["note"] = "No finished fixed_timing + adaptive_network pair is recorded for this scenario."
    return context
