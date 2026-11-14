"""Strict fixed/adaptive comparison for an identical SUMO scenario."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Sequence

from backend.controller.emergency import EMERGENCY_TYPES
from backend.models.analytics_index import upsert_index_entry

from . import analytics
from .runner import REPOSITORY_ROOT


def read_expected_vehicle_ids(config: Path) -> set[str]:
    """Read explicit route IDs; benchmark demand must not be generated at runtime."""
    root = ET.parse(config).getroot()
    route_files = root.findall("./input/route-files")
    if not route_files:
        raise ValueError("SUMO config has no route-files input")
    ids: set[str] = set()
    for entry in route_files:
        value = entry.attrib.get("value", "")
        for route_file in value.split(","):
            route_root = ET.parse((config.parent / route_file.strip()).resolve()).getroot()
            if route_root.findall("flow"):
                raise ValueError("benchmark demand must use explicit vehicle IDs, not flows")
            for vehicle in route_root.findall("vehicle"):
                vehicle_id = vehicle.attrib.get("id")
                if not vehicle_id or vehicle_id in ids:
                    raise ValueError("route demand has a missing or duplicate vehicle ID")
                ids.add(vehicle_id)
    if not ids:
        raise ValueError("benchmark demand has no explicit vehicles")
    return ids


def read_tripinfo(path: Path) -> dict[str, Any]:
    """Keep incomplete and duplicate records visible to strict validation."""
    records: list[dict[str, Any]] = []
    for item in ET.parse(path).getroot().iter("tripinfo"):
        vehicle_id = item.attrib.get("id")
        if not vehicle_id:
            raise ValueError("tripinfo record has no vehicle ID")
        records.append({
            "vehicle_id": vehicle_id,
            "completed": float(item.get("arrival", "-1")) >= 0,
            "waiting_s": float(item.get("waitingTime", "0")),
            "time_loss_s": float(item.get("timeLoss", "0")),
            "duration_s": float(item.get("duration", "0")),
            # Additive fields for the analytics export; comparisons ignore them.
            "vehicle_type": item.get("vType"),
            "depart_s": float(item.attrib["depart"]) if "depart" in item.attrib else None,
            "arrival_s": float(item.attrib["arrival"]) if "arrival" in item.attrib else None,
        })
    completed_records = [record for record in records if record["completed"]]
    completed_ids = [record["vehicle_id"] for record in completed_records]
    all_ids = [record["vehicle_id"] for record in records]
    duplicates = sorted({item for item in all_ids if all_ids.count(item) > 1})
    unfinished_ids = sorted(record["vehicle_id"] for record in records if not record["completed"])
    return {
        "completed": {record["vehicle_id"]: record for record in completed_records},
        "completed_ids": set(completed_ids),
        "unfinished_ids": unfinished_ids,
        "duplicate_ids": duplicates,
        "record_count": len(records),
    }


def read_trips(path: Path) -> dict[str, dict[str, float]]:
    """Backward-compatible completed-trip view for callers that only need metrics."""
    return read_tripinfo(path)["completed"]


def compare(fixed: dict[str, dict[str, float]], adaptive: dict[str, dict[str, float]]) -> dict[str, Any]:
    if not fixed or fixed.keys() != adaptive.keys():
        raise ValueError("completed vehicle IDs differ between runs; results are not comparable")
    count = len(fixed)
    result: dict[str, Any] = {"matched_vehicles": count}
    for field in ("waiting_s", "time_loss_s", "duration_s"):
        fixed_total = sum(trip[field] for trip in fixed.values())
        adaptive_total = sum(trip[field] for trip in adaptive.values())
        absolute_improvement = fixed_total - adaptive_total
        percentage_improvement = (
            round(100 * absolute_improvement / fixed_total, 2) if fixed_total else None
        )
        result[field] = {
            "fixed_total": round(fixed_total, 3),
            "adaptive_total": round(adaptive_total, 3),
            "fixed_average": round(fixed_total / count, 3),
            "adaptive_average": round(adaptive_total / count, 3),
            "absolute_improvement": round(absolute_improvement, 3),
            "percentage_improvement": percentage_improvement,
            # Retain original names for existing callers.
            "average_saved": round(absolute_improvement / count, 3),
            "total_saved": round(absolute_improvement, 3),
            "percent_saved": percentage_improvement,
        }
    return result


def validate_run(
    run: dict[str, Any], tripinfo: dict[str, Any], expected_ids: set[str]
) -> dict[str, Any]:
    """Return all validation failures instead of silently filtering bad runs."""
    departed_ids = run.get("departed_vehicle_ids", [])
    arrived_ids = run.get("arrived_vehicle_ids", [])
    errors: list[str] = []
    if run.get("exit_code") != 0:
        errors.append(f"cycle_run exited {run.get('exit_code')}")
    if run.get("terminated_by_step_limit"):
        errors.append("simulation reached the configured step limit")
    for label, ids in (("departed", departed_ids), ("arrived", arrived_ids)):
        if len(ids) != len(set(ids)):
            errors.append(f"{label} vehicle IDs are not unique")
        if set(ids) != expected_ids:
            errors.append(f"{label} vehicle IDs differ from expected demand")
    if run.get("departed") != len(expected_ids) or run.get("arrived") != len(expected_ids):
        errors.append("reported departed/arrived counts do not equal expected demand")
    if run.get("collisions", 0) or run.get("teleports", 0):
        errors.append("run reported collisions or teleports")
    if tripinfo["duplicate_ids"]:
        errors.append("tripinfo contains duplicate vehicle IDs")
    if tripinfo["unfinished_ids"]:
        errors.append("tripinfo contains unfinished vehicles")
    if tripinfo["completed_ids"] != expected_ids:
        errors.append("completed tripinfo IDs differ from expected demand")
    return {
        "passed": not errors,
        "errors": errors,
        "expected_vehicle_count": len(expected_ids),
        "departed_vehicle_count": len(departed_ids),
        "arrived_vehicle_count": len(arrived_ids),
        "completed_trip_count": len(tripinfo["completed_ids"]),
        "unfinished_vehicle_count": len(tripinfo["unfinished_ids"]),
        "duplicate_tripinfo_ids": tripinfo["duplicate_ids"],
    }


def benchmark_root(config: Path) -> Path:
    scenario_root = config.parent.parent if config.parent.name == "configs" else config.parent
    return scenario_root / "output" / f"comparison_{config.stem}"


def manifest_metadata(manifest: Path) -> dict[str, Any]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if "discovery" in data:
        discovery = data["discovery"]
        expected = set(discovery.get("expected_controller_ids", []))
        excluded = set(discovery.get("excluded_controllers", {}))
        controller_ids = sorted(expected - excluded)
    else:
        controller_ids = sorted(
            item["traffic_light_id"] for item in data.get("controllers", [])
        )
    if not controller_ids:
        raise ValueError("adaptive manifest identifies no active controllers")
    return {
        "profile_id": str(data.get("profile_id", "configured_controllers_only")),
        "controller_ids": controller_ids,
        "controller_count": len(controller_ids),
    }


def config_metadata(
    config: Path, expected_ids: set[str], manifest: Path,
    adaptive: dict[str, Any],
) -> dict[str, Any]:
    root = ET.parse(config).getroot()
    network = root.find("./input/net-file")
    routes = root.findall("./input/route-files")
    seed = root.find("./random_number/seed")
    return {
        "config_path": str(config),
        "network_path": str((config.parent / network.attrib["value"]).resolve()) if network is not None else None,
        "route_files": [str((config.parent / entry.attrib["value"]).resolve()) for entry in routes],
        "seed": int(seed.attrib["value"]) if seed is not None else None,
        "expected_vehicle_count": len(expected_ids),
        "expected_vehicle_ids_sha256": hashlib.sha256(
            "\n".join(sorted(expected_ids)).encode("utf-8")
        ).hexdigest(),
        "adaptive_manifest_path": str(manifest),
        "adaptive_profile_id": adaptive["profile_id"],
        "adaptive_traffic_light_ids": adaptive["controller_ids"],
        "adaptive_controller_count": adaptive["controller_count"],
    }


def validate_adaptive_scope(
    run: dict[str, Any], expected: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    actual_ids = run.get("adaptive_controller_ids", [])
    if len(actual_ids) != len(set(actual_ids)):
        errors.append("adaptive controller IDs are not unique")
    if set(actual_ids) != set(expected["controller_ids"]):
        errors.append("adaptive controller IDs differ from the selected manifest")
    if run.get("adaptive_profile_id") != expected["profile_id"]:
        errors.append("adaptive profile ID differs from the selected manifest")
    return errors


def run_mode(
    config: Path, manifest: Path, mode: str, output: Path, sumo_binary: str, max_steps: int,
    analytics_samples: Path | None = None,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "backend.simulation.cycle_run",
        "--config", str(config), "--sumo-binary", sumo_binary,
        "--output-directory", str(output), "--max-steps", str(max_steps),
    ]
    if mode == "adaptive":
        command.extend(["--adaptive-manifest", str(manifest)])
    if analytics_samples is not None:
        command.extend(["--analytics-samples", str(analytics_samples)])
    completed = subprocess.run(
        command, cwd=REPOSITORY_ROOT, text=True, capture_output=True, check=False
    )
    (output / "cycle_run.stdout.json").write_text(completed.stdout, encoding="utf-8")
    (output / "cycle_run.stderr.log").write_text(completed.stderr, encoding="utf-8")
    try:
        result = json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{mode} run did not produce JSON output") from exc
    result["exit_code"] = completed.returncode
    return result


ANALYTICS_SCHEMA_VERSION = "1.0"
MODES = ("fixed", "adaptive")
# (analytics key, compare() field, compare() statistic)
_PAIRED_TRIP_METRICS = (
    ("total_waiting_time_s", "waiting_s", "total"),
    ("average_waiting_time_s", "waiting_s", "average"),
    ("total_time_loss_s", "time_loss_s", "total"),
    ("average_time_loss_s", "time_loss_s", "average"),
    ("average_trip_duration_s", "duration_s", "average"),
)
_DISTRIBUTION_FIELDS = (
    ("waiting_time_s", "waiting_s"),
    ("time_loss_s", "time_loss_s"),
    ("trip_duration_s", "duration_s"),
)


def _repository_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    path = Path(value).resolve()
    try:
        return path.relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return str(path)


def config_begin_s(config: Path) -> float:
    """Scenario begin time; SUMO's documented default is 0 when unset."""
    begin = ET.parse(config).getroot().find("./time/begin")
    return float(begin.attrib["value"]) if begin is not None else 0.0


def _paired_trip_metrics(comparison: dict[str, Any] | None) -> dict[str, Any]:
    """Reuse compare() exactly; averages keep its per-vehicle saving."""
    result: dict[str, Any] = {}
    for key, field, statistic in _PAIRED_TRIP_METRICS:
        if comparison is None:
            result[key] = analytics.paired(None, None)
            continue
        item = comparison[field]
        result[key] = {
            "fixed": item[f"fixed_{statistic}"],
            "adaptive": item[f"adaptive_{statistic}"],
            "absolute_improvement": (
                item["absolute_improvement"] if statistic == "total" else item["average_saved"]
            ),
            "percentage_improvement": item["percentage_improvement"],
            "better": "lower",
        }
    return result


def _run_validation_summary(run: dict[str, Any] | None, result: dict[str, Any]) -> dict[str, Any]:
    """Benchmark-snapshot validation shape plus the full error list."""
    run = run or {}
    duplicates = result.get("duplicate_tripinfo_ids")
    return {
        "passed": bool(result.get("passed")),
        "errors": list(result.get("errors", [])),
        "departed": run.get("departed"),
        "arrived": run.get("arrived"),
        "completed": result.get("completed_trip_count"),
        "unfinished": result.get("unfinished_vehicle_count"),
        "duplicate_tripinfo_ids": len(duplicates) if duplicates is not None else None,
        "collisions": run.get("collisions"),
        "teleports": run.get("teleports"),
        "process_exit_code": run.get("exit_code"),
        "terminated_by_step_limit": run.get("terminated_by_step_limit"),
    }


def build_analytics_report(
    *,
    scenario_id: str,
    scenario_name: str,
    config: Path,
    manifest: Path,
    expected_ids: set[str],
    adaptive_metadata: dict[str, Any],
    runs: dict[str, dict[str, Any]],
    tripinfos: dict[str, dict[str, Any]],
    validation: dict[str, dict[str, Any]],
    samples: dict[str, dict[str, Any] | None],
    report_path: Path,
    adaptive_label: str | None = None,
    extra_limitations: Sequence[str] = (),
    created_on: str | None = None,
) -> dict[str, Any]:
    """Assemble the static analytics document; failures stay visible, never hidden."""
    limitations = [
        "Eclipse SUMO simulation output; not field measurements and not a certified road controller.",
        "Queues are SUMO halting vehicles (speed below 0.1 m/s) summed once per unique "
        "traffic-light-controlled lane, sampled every simulation step; they are not camera counts.",
        "Mean green is the mean duration of completed phases containing a G/g and no y/Y signal; "
        "the phase still running at the end is excluded.",
        "Throughput is completed trips per hour between the scenario begin time and the last arrival.",
    ]
    completed = {mode: tripinfos[mode]["completed"] for mode in MODES if mode in tripinfos}
    records = {mode: list(trips.values()) for mode, trips in completed.items()}
    comparison = None
    if len(completed) == len(MODES):
        try:
            comparison = compare(completed["fixed"], completed["adaptive"])
        except ValueError as exc:
            limitations.append(f"Paired trip metrics are null: {exc}.")
    else:
        limitations.append("Paired trip metrics are null because a run produced no tripinfo.")

    valid = all(validation.get(mode, {}).get("passed") for mode in MODES)
    if not valid:
        limitations.append(
            "Validation failed; values are exported for inspection and are not a valid "
            "fixed-vs-adaptive comparison."
        )
    for mode in MODES:
        teleports = (runs.get(mode) or {}).get("teleports")
        if teleports:
            limitations.append(f"The {mode} run reported {teleports} teleport(s).")
        if samples.get(mode) is None:
            limitations.append(
                f"Per-step samples are missing for the {mode} run; its queue, time-series and "
                "intersection values are null."
            )

    begin_s = config_begin_s(config)
    throughput = {
        mode: analytics.throughput_vehicles_per_hour(records.get(mode), begin_s) for mode in MODES
    }
    queues = {mode: analytics.network_queue_stats(samples.get(mode)) for mode in MODES}
    summary = _paired_trip_metrics(comparison)
    summary["throughput_vehicles_per_hour"] = analytics.paired(
        throughput["fixed"], throughput["adaptive"], better="higher"
    )
    summary["mean_network_queue_vehicles"] = analytics.paired(
        queues["fixed"]["mean"], queues["adaptive"]["mean"]
    )
    summary["max_network_queue_vehicles"] = analytics.paired(
        queues["fixed"]["max"], queues["adaptive"]["max"]
    )

    durations = [
        sample["steps"][-1]["t_s"] for sample in samples.values() if sample and sample["steps"]
    ]
    interval = analytics.timeseries_interval(durations)
    if interval != analytics.DEFAULT_INTERVAL_S:
        limitations.append(f"Time series downsampled to one sample per {interval:g} s.")
    timeseries: dict[str, Any] = {
        "interval_s": interval,
        "queue_measurement": analytics.QUEUE_MEASUREMENT,
    }
    for mode in MODES:
        sample = samples.get(mode)
        timeseries[mode] = analytics.downsample(sample["steps"], interval) if sample else None

    distributions = {
        key: analytics.distribution(
            {mode: [record[field] for record in values] for mode, values in records.items()},
            MODES,
        )
        for key, field in _DISTRIBUTION_FIELDS
    }

    intersections: dict[str, Any] = {"queue_measurement": analytics.QUEUE_MEASUREMENT}
    for mode in MODES:
        run = runs.get(mode)
        intersections[mode] = analytics.intersection_stats(
            samples.get(mode), run.get("cycle_decision_events") if run else None
        )

    emergency_by_mode = {
        mode: analytics.emergency_stats(records.get(mode), EMERGENCY_TYPES) for mode in MODES
    }
    has_emergency = any(item and item["emergency_trip_count"] for item in emergency_by_mode.values())
    emergency = (
        {"vehicle_types": sorted(EMERGENCY_TYPES), **emergency_by_mode} if has_emergency else None
    )

    metadata = config_metadata(config, expected_ids, manifest, adaptive_metadata)
    adaptive_run = runs.get("adaptive") or {}
    active_ids = adaptive_run.get("adaptive_controller_ids")
    fixed_controllers = adaptive_run.get("fixed_controllers") or {}
    total_tls = next(
        (len(sample["traffic_light_ids"]) for sample in samples.values() if sample), None
    )
    if active_ids is None:
        scope = (
            f"The adaptive run did not report its controllers; manifest profile "
            f"'{adaptive_metadata['profile_id']}' lists {adaptive_metadata['controller_count']}."
        )
    else:
        of_total = f" of {total_tls}" if total_tls is not None else ""
        scope = (
            f"{len(active_ids)}{of_total} traffic-light controllers ran the "
            f"'{adaptive_metadata['profile_id']}' profile in the adaptive run"
        )
        if fixed_controllers:
            scope += f"; kept on fixed timing: {', '.join(sorted(fixed_controllers))}"
        scope += "."

    route_files = [_repository_path(path) for path in metadata["route_files"]]
    return {
        "schema_version": ANALYTICS_SCHEMA_VERSION,
        "kind": "simulation",
        "scenario_id": scenario_id,
        "scenario_name": scenario_name,
        "provenance": {
            "authoritative_report": _repository_path(report_path),
            "config": _repository_path(config),
            "network": _repository_path(metadata["network_path"]),
            "routes": ",".join(path for path in route_files if path),
            "adaptive_manifest": _repository_path(manifest),
            "seed": metadata["seed"],
            "expected_vehicle_count": metadata["expected_vehicle_count"],
            "expected_vehicle_ids_sha256": metadata["expected_vehicle_ids_sha256"],
            "snapshot_created_on": created_on or datetime.date.today().isoformat(),
        },
        "experiment": {
            "fixed_label": "Fixed timing",
            "adaptive_label": adaptive_label or "Adaptive",
            "adaptive_scope": scope,
            "controlled_difference": (
                "Both runs use the same SUMO config, network, routes, seed and vehicle behavior; "
                "only signal control at the adaptive controllers differs."
            ),
            "adaptive_controller_count": len(active_ids) if active_ids is not None else None,
        },
        "runs": {
            mode: {
                "steps": (runs.get(mode) or {}).get("steps"),
                "cycle_decisions": (runs.get(mode) or {}).get("cycle_decisions"),
            }
            for mode in MODES
        },
        "summary": summary,
        "timeseries": timeseries,
        "distributions": distributions,
        "intersections": intersections,
        "emergency": emergency,
        "validation": {
            "passed": valid,
            "matched_vehicle_count": comparison["matched_vehicles"] if comparison else None,
            "errors": [
                f"{mode}: {error}"
                for mode in MODES
                for error in validation.get(mode, {}).get("errors", [])
            ],
            **{
                mode: _run_validation_summary(runs.get(mode), validation.get(mode, {}))
                for mode in MODES
            },
        },
        "limitations": [*limitations, *extra_limitations],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--adaptive-manifest", type=Path, required=True)
    parser.add_argument("--sumo-binary", default="sumo")
    parser.add_argument("--max-steps", type=int, default=5000)
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--output-directory", type=Path,
                        help="separate ignored root for fixed/adaptive raw outputs")
    parser.add_argument("--scenario-id", help="stable public scenario ID")
    parser.add_argument("--benchmark-label", default="fixed_vs_adaptive")
    parser.add_argument("--analytics-out", type=Path,
                        help="also write the static analytics JSON (frontend/public/analytics/<id>.json)")
    parser.add_argument("--analytics-index", type=Path,
                        help="register --analytics-out in this index.json")
    parser.add_argument("--scenario-name", help="display name for the analytics export")
    parser.add_argument("--adaptive-label", help="adaptive-mode label for the analytics export")
    parser.add_argument("--analytics-limitation", action="append", default=[],
                        help="extra limitation sentence for the analytics export (repeatable)")
    args = parser.parse_args()
    if args.analytics_index is not None and args.analytics_out is None:
        parser.error("--analytics-index requires --analytics-out")
    config = args.config.resolve()
    manifest = args.adaptive_manifest.resolve()
    if not config.is_file() or not manifest.is_file() or args.max_steps <= 0:
        parser.error("config and adaptive manifest must exist and max-steps must be positive")

    expected_ids = read_expected_vehicle_ids(config)
    adaptive_metadata = manifest_metadata(manifest)
    base = (args.output_directory.resolve() if args.output_directory else benchmark_root(config))
    report_path = (args.report_path or base / "comparison_report.json").resolve()
    runs: dict[str, dict[str, Any]] = {}
    tripinfos: dict[str, dict[str, Any]] = {}
    validation: dict[str, dict[str, Any]] = {}
    for mode in ("fixed", "adaptive"):
        output = base / mode
        samples_path = output / "analytics_samples.json" if args.analytics_out else None
        if samples_path is not None and samples_path.exists():
            samples_path.unlink()  # never reuse samples from an earlier run
        try:
            runs[mode] = run_mode(
                config, manifest, mode, output, args.sumo_binary, args.max_steps,
                analytics_samples=samples_path,
            )
            tripinfos[mode] = read_tripinfo(output / "tripinfo.xml")
            validation[mode] = validate_run(runs[mode], tripinfos[mode], expected_ids)
            if mode == "adaptive":
                scope_errors = validate_adaptive_scope(runs[mode], adaptive_metadata)
                validation[mode]["errors"].extend(scope_errors)
                validation[mode]["passed"] = not validation[mode]["errors"]
        except (OSError, RuntimeError, ValueError, ET.ParseError) as exc:
            validation[mode] = {"passed": False, "errors": [str(exc)]}

    valid = all(item.get("passed") for item in validation.values())
    comparison = (
        compare(tripinfos["fixed"]["completed"], tripinfos["adaptive"]["completed"])
        if valid
        else None
    )
    report = {
        "schema_version": "1.0",
        "benchmark": args.benchmark_label,
        "scenario_id": args.scenario_id or config.stem,
        "input": config_metadata(
            config, expected_ids, manifest, adaptive_metadata
        ),
        "max_steps": args.max_steps,
        "validation": {"passed": valid, "runs": validation},
        "runs": {
            mode: {
                key: value
                for key, value in run.items()
                if key not in {"departed_vehicle_ids", "arrived_vehicle_ids"}
            }
            for mode, run in runs.items()
        },
        "comparison": comparison,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if args.analytics_out is not None:
        write_analytics_export(args, config, manifest, expected_ids, adaptive_metadata,
                               runs, tripinfos, validation, base, report_path)
    return 0 if valid else 1


def write_analytics_export(
    args: argparse.Namespace, config: Path, manifest: Path, expected_ids: set[str],
    adaptive_metadata: dict[str, Any], runs: dict[str, dict[str, Any]],
    tripinfos: dict[str, dict[str, Any]], validation: dict[str, dict[str, Any]],
    base: Path, report_path: Path,
) -> None:
    samples: dict[str, dict[str, Any] | None] = {}
    extra = list(args.analytics_limitation)
    for mode in MODES:
        try:
            samples[mode] = analytics.read_samples(base / mode / "analytics_samples.json")
        except (OSError, ValueError) as exc:
            samples[mode] = None
            extra.append(f"The {mode} per-step samples could not be read: {exc}.")
    scenario_id = args.scenario_id or config.stem
    document = build_analytics_report(
        scenario_id=scenario_id,
        scenario_name=args.scenario_name or scenario_id,
        config=config, manifest=manifest, expected_ids=expected_ids,
        adaptive_metadata=adaptive_metadata, runs=runs, tripinfos=tripinfos,
        validation=validation, samples=samples, report_path=report_path,
        adaptive_label=args.adaptive_label, extra_limitations=extra,
    )
    out = args.analytics_out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    print(f"analytics written to {out} ({out.stat().st_size} bytes)", file=sys.stderr)
    if args.analytics_index is not None:
        upsert_index_entry(args.analytics_index, entry_id=out.stem,
                           label=document["scenario_name"], kind="simulation", file_path=out)


if __name__ == "__main__":
    raise SystemExit(main())
