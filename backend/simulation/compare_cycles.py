"""Strict fixed/adaptive comparison for an identical SUMO scenario."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

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


def config_metadata(config: Path, expected_ids: set[str], manifest: Path) -> dict[str, Any]:
    root = ET.parse(config).getroot()
    network = root.find("./input/net-file")
    routes = root.findall("./input/route-files")
    seed = root.find("./random_number/seed")
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
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
        "adaptive_traffic_light_ids": [
            item["traffic_light_id"] for item in manifest_data.get("controllers", [])
        ],
    }


def run_mode(
    config: Path, manifest: Path, mode: str, output: Path, sumo_binary: str, max_steps: int
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "backend.simulation.cycle_run",
        "--config", str(config), "--sumo-binary", sumo_binary,
        "--output-directory", str(output), "--max-steps", str(max_steps),
    ]
    if mode == "adaptive":
        command.extend(["--adaptive-manifest", str(manifest)])
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--adaptive-manifest", type=Path, required=True)
    parser.add_argument("--sumo-binary", default="sumo")
    parser.add_argument("--max-steps", type=int, default=5000)
    parser.add_argument("--report-path", type=Path)
    args = parser.parse_args()
    config = args.config.resolve()
    manifest = args.adaptive_manifest.resolve()
    if not config.is_file() or not manifest.is_file() or args.max_steps <= 0:
        parser.error("config and adaptive manifest must exist and max-steps must be positive")

    expected_ids = read_expected_vehicle_ids(config)
    base = benchmark_root(config)
    report_path = (args.report_path or base / "comparison_report.json").resolve()
    runs: dict[str, dict[str, Any]] = {}
    tripinfos: dict[str, dict[str, Any]] = {}
    validation: dict[str, dict[str, Any]] = {}
    for mode in ("fixed", "adaptive"):
        output = base / mode
        try:
            runs[mode] = run_mode(
                config, manifest, mode, output, args.sumo_binary, args.max_steps
            )
            tripinfos[mode] = read_tripinfo(output / "tripinfo.xml")
            validation[mode] = validate_run(runs[mode], tripinfos[mode], expected_ids)
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
        "benchmark": "london_fixed_vs_adaptive",
        "scenario_id": "london_unbalanced",
        "input": config_metadata(config, expected_ids, manifest),
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
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
