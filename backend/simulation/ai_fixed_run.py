"""Generate AI-derived demand and run an isolated fixed-control SUMO experiment."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from backend.simulation.ai_demand import DEFAULT_NETWORK_PATH, generate_demand
from backend.simulation.ai_input import JsonlValidationError


STEP_LENGTH_S = 1.0
DEFAULT_MAX_SIMULATION_TIME_S = 1800.0
DEFAULT_TELEPORT_THRESHOLD_S = 300.0


def _add_value(parent: ET.Element, name: str, value: object) -> None:
    ET.SubElement(parent, name, {"value": str(value).lower() if isinstance(value, bool) else str(value)})


def write_runtime_config(
    path: Path,
    *,
    network_path: Path,
    route_path: Path,
    tripinfo_path: Path,
    summary_path: Path,
    collision_path: Path,
    max_simulation_time_s: float,
) -> None:
    """Write a standalone config that uses the network's unchanged fixed program."""
    root = ET.Element("configuration", {
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:noNamespaceSchemaLocation": "https://sumo.dlr.de/xsd/sumoConfiguration.xsd",
    })
    inputs = ET.SubElement(root, "input")
    _add_value(inputs, "net-file", network_path.resolve())
    _add_value(inputs, "route-files", route_path.resolve())
    time = ET.SubElement(root, "time")
    _add_value(time, "begin", 0)
    _add_value(time, "end", _format_number(max_simulation_time_s))
    _add_value(time, "step-length", _format_number(STEP_LENGTH_S))
    random_number = ET.SubElement(root, "random_number")
    _add_value(random_number, "seed", 42)
    output = ET.SubElement(root, "output")
    _add_value(output, "tripinfo-output", tripinfo_path.resolve())
    _add_value(output, "tripinfo-output.write-unfinished", True)
    _add_value(output, "summary-output", summary_path.resolve())
    _add_value(output, "summary-output.period", 1)
    _add_value(output, "collision-output", collision_path.resolve())
    processing = ET.SubElement(root, "processing")
    _add_value(processing, "collision.action", "warn")
    _add_value(processing, "collision.check-junctions", True)
    _add_value(processing, "time-to-teleport", _format_number(DEFAULT_TELEPORT_THRESHOLD_S))
    report = ET.SubElement(root, "report")
    _add_value(report, "verbose", False)
    _add_value(report, "no-step-log", True)
    ET.indent(root, space="    ")
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def _format_number(value: float) -> str:
    return format(value, ".15g")


def read_planned_demand(path: Path) -> dict[str, float]:
    planned: dict[str, float] = {}
    for vehicle in ET.parse(path).getroot().findall("vehicle"):
        vehicle_id = vehicle.get("id")
        if not vehicle_id or vehicle_id in planned:
            raise JsonlValidationError("generated demand has missing or duplicate vehicle IDs")
        planned[vehicle_id] = float(vehicle.get("depart", "nan"))
    return planned


def read_fixed_program(network_path: Path) -> dict[str, Any]:
    """Confirm the runtime network retains the checked-in static fixed program."""
    root = ET.parse(network_path).getroot()
    programs = [
        logic for logic in root.findall("tlLogic")
        if logic.get("id") == "demo_01" and logic.get("programID") == "fixed"
    ]
    if len(programs) != 1 or programs[0].get("type") != "static":
        raise JsonlValidationError("synthetic network does not contain demo_01 static fixed program")
    phases = [
        {
            "duration_s": float(phase.get("duration", "nan")),
            "state": phase.get("state"),
            "name": phase.get("name"),
        }
        for phase in programs[0].findall("phase")
    ]
    if not phases:
        raise JsonlValidationError("demo_01 fixed program has no phases")
    return {"traffic_light_id": "demo_01", "program_id": "fixed", "phases": phases}


def read_tripinfo(path: Path, planned: dict[str, float]) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for trip in ET.parse(path).getroot().iter("tripinfo"):
        vehicle_id = trip.get("id")
        if vehicle_id is None or vehicle_id in seen:
            errors.append("tripinfo contains a missing or duplicate vehicle ID")
            continue
        seen.add(vehicle_id)
        if vehicle_id not in planned:
            errors.append(f"tripinfo contains unexpected vehicle {vehicle_id}")
            continue
        actual_depart = float(trip.get("depart", "-1"))
        arrival = float(trip.get("arrival", "-1"))
        records.append({
            "vehicle_id": vehicle_id,
            "planned_depart_s": planned[vehicle_id],
            "actual_depart_s": actual_depart if actual_depart >= 0 else None,
            "insertion_delay_s": (
                round(actual_depart - planned[vehicle_id], 6) if actual_depart >= 0 else None
            ),
            "arrived": arrival >= 0,
            "arrival_s": arrival if arrival >= 0 else None,
            "waiting_time_s": float(trip.get("waitingTime", "0")),
            "time_loss_s": float(trip.get("timeLoss", "0")),
            "duration_s": float(trip.get("duration", "0")),
        })
    return records, errors


def read_event_totals(summary_path: Path) -> tuple[int, int, float | None]:
    collisions = teleports = 0
    final_time: float | None = None
    for step in ET.parse(summary_path).getroot().iter("step"):
        collisions += int(step.get("collisions", "0"))
        teleports += int(step.get("teleports", "0"))
        final_time = float(step.get("time", "0"))
    return collisions, teleports, final_time


def run_fixed_experiment(
    counts_path: Path,
    events_path: Path,
    output_directory: Path,
    *,
    network_path: Path = DEFAULT_NETWORK_PATH,
    sumo_binary: str = "sumo",
    max_simulation_time_s: float = DEFAULT_MAX_SIMULATION_TIME_S,
    wall_timeout_s: float = 120.0,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Generate demand, execute SUMO once, and report strict insertion/trip accounting."""
    if max_simulation_time_s <= 264:
        raise ValueError("max simulation time must extend beyond the 264-second recording")
    if wall_timeout_s <= 0:
        raise ValueError("wall timeout must be positive")
    output_directory = output_directory.resolve()
    paths = {
        "routes": output_directory / "ai_demand.rou.xml",
        "demand_summary": output_directory / "ai_demand.summary.json",
        "config": output_directory / "fixed_runtime.sumocfg",
        "tripinfo": output_directory / "tripinfo.xml",
        "summary": output_directory / "summary.xml",
        "collisions": output_directory / "collisions.xml",
        "stdout": output_directory / "sumo.stdout.log",
        "stderr": output_directory / "sumo.stderr.log",
        "accounting": output_directory / "insertion_accounting.jsonl",
        "report": output_directory / "fixed_run_summary.json",
    }
    existing = [path for path in paths.values() if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"refusing to overwrite runtime output: {existing[0]}")
    output_directory.mkdir(parents=True, exist_ok=True)
    fixed_program = read_fixed_program(network_path)
    demand_summary = generate_demand(
        counts_path,
        events_path,
        paths["routes"],
        summary_path=paths["demand_summary"],
        network_path=network_path,
        overwrite=overwrite,
    )
    write_runtime_config(
        paths["config"],
        network_path=network_path,
        route_path=paths["routes"],
        tripinfo_path=paths["tripinfo"],
        summary_path=paths["summary"],
        collision_path=paths["collisions"],
        max_simulation_time_s=max_simulation_time_s,
    )
    try:
        completed = subprocess.run(
            [sumo_binary, "-c", str(paths["config"])],
            text=True,
            capture_output=True,
            check=False,
            timeout=wall_timeout_s,
        )
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        completed = subprocess.CompletedProcess(
            exc.cmd, -1, stdout, stderr
        )
        timed_out = True
    paths["stdout"].write_text(completed.stdout, encoding="utf-8")
    paths["stderr"].write_text(completed.stderr, encoding="utf-8")

    planned = read_planned_demand(paths["routes"])
    validation_errors: list[str] = []
    records: list[dict[str, Any]] = []
    if not paths["tripinfo"].is_file() or not paths["summary"].is_file():
        validation_errors.append("SUMO did not produce tripinfo and summary outputs")
    else:
        records, trip_errors = read_tripinfo(paths["tripinfo"], planned)
        validation_errors.extend(trip_errors)
    record_by_id = {record["vehicle_id"]: record for record in records}
    inserted_ids = {
        vehicle_id for vehicle_id, record in record_by_id.items()
        if record["actual_depart_s"] is not None
    }
    arrived_ids = {
        vehicle_id for vehicle_id, record in record_by_id.items() if record["arrived"]
    }
    failed_insertion_ids = sorted(set(planned) - inserted_ids)
    unfinished_ids = sorted(set(planned) - arrived_ids)
    if completed.returncode != 0:
        validation_errors.append(f"SUMO exited with code {completed.returncode}")
    if timed_out:
        validation_errors.append("SUMO exceeded the wall-clock timeout")
    if inserted_ids != set(planned):
        validation_errors.append("inserted vehicle IDs differ from planned demand")
    if arrived_ids != set(planned):
        validation_errors.append("not every planned vehicle arrived")

    collision_vehicle_events = teleports = 0
    final_time: float | None = None
    if paths["summary"].is_file():
        collision_vehicle_events, teleports, final_time = read_event_totals(paths["summary"])
    collision_records = (
        len(list(ET.parse(paths["collisions"]).getroot().iter("collision")))
        if paths["collisions"].is_file()
        else 0
    )
    if collision_records:
        validation_errors.append(f"SUMO reported {collision_records} collisions")
    if teleports:
        validation_errors.append(f"SUMO reported {teleports} teleports")

    delays = [
        float(record["insertion_delay_s"])
        for record in records if record["insertion_delay_s"] is not None
    ]
    capacity_delayed = [delay for delay in delays if delay > STEP_LENGTH_S + 1e-6]
    actual_departures = [
        float(record["actual_depart_s"])
        for record in records if record["actual_depart_s"] is not None
    ]
    arrival_times = [
        float(record["arrival_s"])
        for record in records if record["arrival_s"] is not None
    ]
    accounting_lines = [json.dumps(record, sort_keys=True) for record in records]
    paths["accounting"].write_text(
        "\n".join(accounting_lines) + ("\n" if accounting_lines else ""),
        encoding="utf-8",
    )
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment": "ai_demand_single_intersection_fixed",
        "control_mode": "fixed",
        "traffic_light_program": "existing demo_01 fixed program; timings unchanged",
        "fixed_program": fixed_program,
        "validation": {
            "passed": not validation_errors,
            "errors": validation_errors,
            "sumo_exit_code": completed.returncode,
            "wall_timeout_reached": timed_out,
            "maximum_simulation_time_s": max_simulation_time_s,
            "final_recorded_simulation_time_s": final_time,
        },
        "demand": demand_summary,
        "vehicles": {
            "planned": len(planned),
            "inserted": len(inserted_ids),
            "arrived": len(arrived_ids),
            "failed_insertions": len(failed_insertion_ids),
            "failed_insertion_ids": failed_insertion_ids,
            "unfinished": len(unfinished_ids),
            "unfinished_ids": unfinished_ids,
            "actual_departure_time_range_s": {
                "first": min(actual_departures, default=None),
                "last": max(actual_departures, default=None),
            },
            "all_completed_by_simulation_time_s": max(arrival_times, default=None),
        },
        "insertion_delay": {
            "definition": "actual SUMO depart minus planned AI video timestamp",
            "vehicles_with_any_delay": sum(delay > 1e-6 for delay in delays),
            "vehicles_delayed_beyond_one_simulation_step": len(capacity_delayed),
            "beyond_one_step_interpretation": "additional insertion-capacity delay beyond ordinary timestep quantization",
            "total_delay_s": round(sum(delays), 3),
            "maximum_delay_s": round(max(delays, default=0.0), 3),
            "simulation_step_s": STEP_LENGTH_S,
        },
        "trip_metrics": {
            "scope": "all completed vehicles" if len(arrived_ids) == len(planned) else "available tripinfo records",
            "total_waiting_time_s": round(sum(float(item["waiting_time_s"]) for item in records), 3),
            "total_time_loss_s": round(sum(float(item["time_loss_s"]) for item in records), 3),
            "average_waiting_time_s": (
                round(sum(float(item["waiting_time_s"]) for item in records) / len(records), 3)
                if records else None
            ),
            "average_time_loss_s": (
                round(sum(float(item["time_loss_s"]) for item in records) / len(records), 3)
                if records else None
            ),
        },
        "diagnostics": {
            "collisions": collision_records,
            "collision_involved_vehicle_events": collision_vehicle_events,
            "teleports": teleports,
            "teleport_threshold_s": DEFAULT_TELEPORT_THRESHOLD_S,
        },
        "limitations": [
            "The 26 vehicles already observed at video t=0 are excluded; their positions are unknown.",
            "Camera-to-SUMO orientation is unverified.",
            "All generated movements are straight-only verified synthetic connections.",
            "AI intersection entry/exit times do not command or remove SUMO vehicles.",
            "Subsecond planned departures may be quantized by the one-second SUMO step.",
        ],
    }
    paths["report"].write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK_PATH)
    parser.add_argument("--sumo-binary", default="sumo")
    parser.add_argument("--max-simulation-time", type=float, default=DEFAULT_MAX_SIMULATION_TIME_S)
    parser.add_argument("--wall-timeout", type=float, default=120.0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        report = run_fixed_experiment(
            args.counts,
            args.events,
            args.output_directory,
            network_path=args.network,
            sumo_binary=args.sumo_binary,
            max_simulation_time_s=args.max_simulation_time,
            wall_timeout_s=args.wall_timeout,
            overwrite=args.overwrite,
        )
    except (FileExistsError, FileNotFoundError, JsonlValidationError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
