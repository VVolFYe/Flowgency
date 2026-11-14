"""Strict paired comparison for the isolated AI-demand SUMO experiments."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from backend.simulation.ai_adaptive_run import run_adaptive_experiment
from backend.simulation.ai_fixed_run import run_fixed_experiment


class ComparisonError(ValueError):
    """The two experiments do not form a valid paired comparison."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComparisonError(f"could not read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ComparisonError(f"{path} must contain a JSON object")
    return value


def read_demand(path: Path) -> dict[str, Any]:
    """Read explicit vehicles and their resolved route edges."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ComparisonError(f"could not read demand {path}: {exc}") from exc
    routes = {
        item.get("id"): item.get("edges")
        for item in root.findall("route")
        if item.get("id")
    }
    vehicles: dict[str, dict[str, Any]] = {}
    for item in root.findall("vehicle"):
        vehicle_id = item.get("id")
        route_id = item.get("route")
        if not vehicle_id or vehicle_id in vehicles:
            raise ComparisonError("demand contains a missing or duplicate vehicle ID")
        if not route_id or route_id not in routes or not routes[route_id]:
            raise ComparisonError(f"vehicle {vehicle_id} has no resolvable route")
        try:
            planned_depart_s = float(item.attrib["depart"])
        except (KeyError, ValueError) as exc:
            raise ComparisonError(f"vehicle {vehicle_id} has invalid departure time") from exc
        vehicles[vehicle_id] = {
            "vehicle_id": vehicle_id,
            "planned_depart_s": planned_depart_s,
            "route_id": route_id,
            "route_edges": routes[route_id],
            "vehicle_type": item.get("type"),
            "depart_lane": item.get("departLane"),
            "depart_speed": item.get("departSpeed"),
            "depart_position": item.get("departPos"),
        }
    if not vehicles:
        raise ComparisonError("demand contains no explicit vehicles")
    semantic = json.dumps(
        [vehicles[key] for key in sorted(vehicles)],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "vehicles": vehicles,
        "file_sha256": _sha256(path),
        "semantic_sha256": hashlib.sha256(semantic).hexdigest(),
    }


def _config_value(root: ET.Element, xpath: str) -> str | None:
    element = root.find(xpath)
    return element.get("value") if element is not None else None


def read_simulation_settings(path: Path) -> dict[str, Any]:
    """Read comparison-relevant settings, excluding output destinations."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ComparisonError(f"could not read SUMO config {path}: {exc}") from exc
    network_value = _config_value(root, "./input/net-file")
    if not network_value:
        raise ComparisonError(f"SUMO config {path} has no network")
    network_path = Path(network_value)
    if not network_path.is_absolute():
        network_path = path.parent / network_path
    network_path = network_path.resolve()
    if not network_path.is_file():
        raise ComparisonError(f"SUMO network does not exist: {network_path}")
    return {
        "network_sha256": _sha256(network_path),
        "begin_s": _config_value(root, "./time/begin"),
        "end_s": _config_value(root, "./time/end"),
        "step_length_s": _config_value(root, "./time/step-length"),
        "seed": _config_value(root, "./random_number/seed"),
        "tripinfo_write_unfinished": _config_value(
            root, "./output/tripinfo-output.write-unfinished"
        ),
        "summary_period_s": _config_value(root, "./output/summary-output.period"),
        "collision_action": _config_value(root, "./processing/collision.action"),
        "collision_check_junctions": _config_value(
            root, "./processing/collision.check-junctions"
        ),
        "time_to_teleport_s": _config_value(
            root, "./processing/time-to-teleport"
        ),
    }


def read_completed_trips(
    path: Path, planned: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Read every trip; unfinished, unknown, or duplicate IDs are fatal."""
    try:
        trips = list(ET.parse(path).getroot().iter("tripinfo"))
    except (OSError, ET.ParseError) as exc:
        raise ComparisonError(f"could not read tripinfo {path}: {exc}") from exc
    records: dict[str, dict[str, Any]] = {}
    unfinished: list[str] = []
    for item in trips:
        vehicle_id = item.get("id")
        if not vehicle_id or vehicle_id in records:
            raise ComparisonError("tripinfo contains a missing or duplicate vehicle ID")
        if vehicle_id not in planned:
            raise ComparisonError(f"tripinfo contains unknown vehicle {vehicle_id}")
        try:
            actual_depart_s = float(item.get("depart", "-1"))
            arrival_s = float(item.get("arrival", "-1"))
            waiting_time_s = float(item.get("waitingTime", "0"))
            time_loss_s = float(item.get("timeLoss", "0"))
        except ValueError as exc:
            raise ComparisonError(f"tripinfo has invalid values for {vehicle_id}") from exc
        if actual_depart_s < 0 or arrival_s < 0:
            unfinished.append(vehicle_id)
        planned_depart_s = float(planned[vehicle_id]["planned_depart_s"])
        records[vehicle_id] = {
            "vehicle_id": vehicle_id,
            "planned_depart_s": planned_depart_s,
            "actual_depart_s": actual_depart_s,
            "arrival_s": arrival_s,
            "insertion_delay_s": actual_depart_s - planned_depart_s,
            "waiting_time_s": waiting_time_s,
            "time_loss_s": time_loss_s,
            "planned_to_arrival_s": arrival_s - planned_depart_s,
        }
    missing = sorted(set(planned) - set(records))
    if unfinished:
        raise ComparisonError(f"tripinfo contains unfinished vehicles: {unfinished[:5]}")
    if missing:
        raise ComparisonError(f"tripinfo is missing planned vehicles: {missing[:5]}")
    return records


def _run_paths(directory: Path, mode: str) -> dict[str, Path]:
    prefix = "fixed" if mode == "fixed" else "adaptive"
    return {
        "report": directory / f"{prefix}_run_summary.json",
        "config": directory / f"{prefix}_runtime.sumocfg",
        "routes": directory / "ai_demand.rou.xml",
        "demand_summary": directory / "ai_demand.summary.json",
        "tripinfo": directory / "tripinfo.xml",
        "summary": directory / "summary.xml",
        "collisions": directory / "collisions.xml",
    }


def read_validated_run(directory: Path, mode: str) -> dict[str, Any]:
    paths = _run_paths(directory.resolve(), mode)
    report = _load_json(paths["report"])
    demand_summary = _load_json(paths["demand_summary"])
    if report.get("control_mode") != mode:
        raise ComparisonError(f"{directory} is not a {mode} experiment")
    if not report.get("validation", {}).get("passed"):
        raise ComparisonError(f"{mode} experiment did not pass its own validation")
    diagnostics = report.get("diagnostics", {})
    if diagnostics.get("collisions") or diagnostics.get("teleports"):
        raise ComparisonError(f"{mode} experiment reported collisions or teleports")

    demand = read_demand(paths["routes"])
    trips = read_completed_trips(paths["tripinfo"], demand["vehicles"])
    if report.get("vehicles", {}).get("planned") != len(demand["vehicles"]):
        raise ComparisonError(f"{mode} report planned count differs from demand")
    for field in ("inserted", "arrived"):
        if report.get("vehicles", {}).get(field) != len(demand["vehicles"]):
            raise ComparisonError(f"{mode} report {field} count is incomplete")
    if report.get("vehicles", {}).get("unfinished"):
        raise ComparisonError(f"{mode} report contains unfinished vehicles")

    try:
        collision_count = len(
            list(ET.parse(paths["collisions"]).getroot().iter("collision"))
        )
        summary_steps = list(ET.parse(paths["summary"]).getroot().iter("step"))
    except (OSError, ET.ParseError) as exc:
        raise ComparisonError(f"could not read {mode} diagnostics: {exc}") from exc
    summary_collisions = sum(int(item.get("collisions", "0")) for item in summary_steps)
    summary_teleports = sum(int(item.get("teleports", "0")) for item in summary_steps)
    if collision_count or summary_collisions or summary_teleports:
        raise ComparisonError(f"{mode} raw diagnostics contain collisions or teleports")

    count = len(trips)
    insertion_total = sum(item["insertion_delay_s"] for item in trips.values())
    planned_arrival_total = sum(
        item["planned_to_arrival_s"] for item in trips.values()
    )
    metrics = {
        "vehicle_count": count,
        "total_waiting_time_s": round(
            sum(item["waiting_time_s"] for item in trips.values()), 3
        ),
        "total_time_loss_s": round(
            sum(item["time_loss_s"] for item in trips.values()), 3
        ),
        "total_insertion_delay_s": round(insertion_total, 3),
        "average_insertion_delay_s": round(insertion_total / count, 3),
        "total_planned_to_arrival_s": round(planned_arrival_total, 3),
        "average_planned_to_arrival_s": round(planned_arrival_total / count, 3),
        "last_vehicle_arrival_s": max(item["arrival_s"] for item in trips.values()),
        "collisions": 0,
        "teleports": 0,
    }
    return {
        "mode": mode,
        "paths": paths,
        "report": report,
        "demand": demand,
        "demand_sources": demand_summary.get("sources"),
        "settings": read_simulation_settings(paths["config"]),
        "trips": trips,
        "metrics": metrics,
    }


def compare_metric(fixed: float, adaptive: float) -> dict[str, Any]:
    """Compare a lower-is-better metric with explicit sign semantics."""
    adaptive_minus_fixed = adaptive - fixed
    improvement = fixed - adaptive
    return {
        "fixed": round(fixed, 3),
        "adaptive": round(adaptive, 3),
        "adaptive_minus_fixed": round(adaptive_minus_fixed, 3),
        "percent_change": round(100 * adaptive_minus_fixed / fixed, 3) if fixed else None,
        "absolute_improvement": round(improvement, 3),
        "improvement_percent": round(100 * improvement / fixed, 3) if fixed else None,
        "outcome": (
            "improvement" if improvement > 0 else "regression" if improvement < 0 else "no_change"
        ),
        "interpretation": "lower_is_better",
    }


def compare_experiments(fixed_directory: Path, adaptive_directory: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    fixed = read_validated_run(fixed_directory, "fixed")
    adaptive = read_validated_run(adaptive_directory, "adaptive")
    errors: list[str] = []
    if fixed["demand"]["file_sha256"] != adaptive["demand"]["file_sha256"]:
        errors.append("route files differ byte-for-byte")
    if fixed["demand"]["semantic_sha256"] != adaptive["demand"]["semantic_sha256"]:
        errors.append("vehicle IDs, departures, routes, or vehicle parameters differ")
    if fixed["demand_sources"] != adaptive["demand_sources"]:
        errors.append("AI input SHA-256 provenance differs")
    if fixed["settings"] != adaptive["settings"]:
        errors.append("network or SUMO simulation settings differ")
    if set(fixed["trips"]) != set(adaptive["trips"]):
        errors.append("completed vehicle ID sets differ")
    if errors:
        raise ComparisonError("; ".join(errors))

    metric_names = (
        "total_waiting_time_s",
        "total_time_loss_s",
        "total_insertion_delay_s",
        "average_insertion_delay_s",
        "total_planned_to_arrival_s",
        "average_planned_to_arrival_s",
        "last_vehicle_arrival_s",
    )
    comparison = {
        name: compare_metric(
            float(fixed["metrics"][name]), float(adaptive["metrics"][name])
        )
        for name in metric_names
    }
    per_vehicle: list[dict[str, Any]] = []
    for vehicle_id in sorted(fixed["trips"]):
        fixed_trip = fixed["trips"][vehicle_id]
        adaptive_trip = adaptive["trips"][vehicle_id]
        route = fixed["demand"]["vehicles"][vehicle_id]
        row: dict[str, Any] = {
            "vehicle_id": vehicle_id,
            "route_id": route["route_id"],
            "route_edges": route["route_edges"],
            "planned_depart_s": route["planned_depart_s"],
        }
        for mode, trip in (("fixed", fixed_trip), ("adaptive", adaptive_trip)):
            for field in (
                "actual_depart_s",
                "arrival_s",
                "insertion_delay_s",
                "waiting_time_s",
                "time_loss_s",
                "planned_to_arrival_s",
            ):
                row[f"{mode}_{field}"] = round(float(trip[field]), 6)
        for field in (
            "arrival_s",
            "insertion_delay_s",
            "waiting_time_s",
            "time_loss_s",
            "planned_to_arrival_s",
        ):
            row[f"adaptive_minus_fixed_{field}"] = round(
                float(adaptive_trip[field]) - float(fixed_trip[field]), 6
            )
        per_vehicle.append(row)

    report = {
        "schema_version": "1.0",
        "experiment": "ai_demand_single_intersection_fixed_vs_adaptive",
        "validation": {
            "passed": True,
            "vehicle_ids_match": True,
            "planned_departures_and_routes_match": True,
            "route_file_sha256_match": True,
            "ai_input_sha256_match": True,
            "network_and_simulation_settings_match": True,
            "all_vehicles_completed": True,
            "collisions": 0,
            "teleports": 0,
        },
        "inputs": {
            "vehicle_count": len(fixed["trips"]),
            "route_file_sha256": fixed["demand"]["file_sha256"],
            "semantic_demand_sha256": fixed["demand"]["semantic_sha256"],
            "ai_sources": fixed["demand_sources"],
            "simulation_settings": fixed["settings"],
        },
        "runs": {
            "fixed": fixed["metrics"],
            "adaptive": adaptive["metrics"],
        },
        "comparison": comparison,
        "sign_convention": {
            "adaptive_minus_fixed": "positive means Adaptive is higher/worse",
            "absolute_improvement": "positive means Adaptive is lower/better",
        },
        "limitations": [
            "The 26 vehicles already observed at video t=0 are excluded.",
            "Camera-to-SUMO orientation is unverified.",
            "The synthetic network supports straight-through movements only.",
            "AI snapshot counts are not direct inputs to the adaptive controller; it uses SUMO queues.",
            "Large pre-insertion capacity delays are reported separately from SUMO waiting time.",
            "This recorded-video synthetic experiment does not establish real-world traffic improvement.",
        ],
    }
    return report, per_vehicle


def format_summary(report: dict[str, Any]) -> str:
    comparison = report["comparison"]
    vehicle_count = report["inputs"]["vehicle_count"]
    lines = [
        "Flowgency AI-demand Fixed vs Adaptive comparison",
        f"VALIDATED: {vehicle_count} matching vehicles completed; 0 collisions; 0 teleports.",
        "",
        "Metric | Fixed | Adaptive | Adaptive - Fixed | Outcome",
    ]
    labels = {
        "total_waiting_time_s": "Total waiting (s)",
        "total_time_loss_s": "Total time loss (s)",
        "total_insertion_delay_s": "Total insertion delay (s)",
        "average_insertion_delay_s": "Average insertion delay (s)",
        "total_planned_to_arrival_s": "Total planned-to-arrival (s)",
        "average_planned_to_arrival_s": "Average planned-to-arrival (s)",
        "last_vehicle_arrival_s": "Last arrival (s)",
    }
    for key, label in labels.items():
        value = comparison[key]
        lines.append(
            f"{label} | {value['fixed']} | {value['adaptive']} | "
            f"{value['adaptive_minus_fixed']} ({value['percent_change']}%) | "
            f"{value['outcome']}"
        )
    lines.extend((
        "",
        "Positive Adaptive - Fixed values are regressions because every metric is lower-is-better.",
        "Insertion delay is separate from SUMO waiting time.",
        "No real-world traffic improvement is claimed.",
    ))
    return "\n".join(lines) + "\n"


def write_outputs(
    output_directory: Path,
    report: dict[str, Any],
    per_vehicle: list[dict[str, Any]],
    *,
    write_csv: bool,
    overwrite: bool,
) -> None:
    output_directory = output_directory.resolve()
    report_path = output_directory / "comparison_report.json"
    summary_path = output_directory / "comparison_summary.txt"
    csv_path = output_directory / "per_vehicle_comparison.csv"
    targets = [report_path, summary_path] + ([csv_path] if write_csv else [])
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"refusing to overwrite comparison output: {existing[0]}")
    output_directory.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary_path.write_text(format_summary(report), encoding="utf-8")
    if write_csv:
        with csv_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(per_vehicle[0]))
            writer.writeheader()
            writer.writerows(per_vehicle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixed-directory", type=Path, required=True)
    parser.add_argument("--adaptive-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--run-experiments", action="store_true")
    parser.add_argument("--counts", type=Path)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--sumo-binary", default="sumo")
    parser.add_argument("--max-simulation-time", type=float, default=1800.0)
    parser.add_argument("--wall-timeout", type=float, default=120.0)
    parser.add_argument("--per-vehicle-csv", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        if args.run_experiments:
            if args.counts is None or args.events is None:
                raise ComparisonError(
                    "--counts and --events are required with --run-experiments"
                )
            fixed_report = run_fixed_experiment(
                args.counts,
                args.events,
                args.fixed_directory,
                sumo_binary=args.sumo_binary,
                max_simulation_time_s=args.max_simulation_time,
                wall_timeout_s=args.wall_timeout,
                overwrite=args.overwrite,
            )
            if not fixed_report["validation"]["passed"]:
                raise ComparisonError("new fixed experiment failed validation")
            adaptive_report = run_adaptive_experiment(
                args.counts,
                args.events,
                args.adaptive_directory,
                sumo_binary=args.sumo_binary,
                max_simulation_time_s=args.max_simulation_time,
                wall_timeout_s=args.wall_timeout,
                fixed_demand_route=args.fixed_directory / "ai_demand.rou.xml",
                overwrite=args.overwrite,
            )
            if not adaptive_report["validation"]["passed"]:
                raise ComparisonError("new adaptive experiment failed validation")
        report, per_vehicle = compare_experiments(
            args.fixed_directory, args.adaptive_directory
        )
        write_outputs(
            args.output_directory,
            report,
            per_vehicle,
            write_csv=args.per_vehicle_csv,
            overwrite=args.overwrite,
        )
    except (ComparisonError, FileExistsError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(format_summary(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
