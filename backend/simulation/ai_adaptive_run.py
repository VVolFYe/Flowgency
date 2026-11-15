"""Run AI-derived demand with the existing synthetic TraCI adaptive controller."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from backend.simulation.ai_demand import (
    DEFAULT_NETWORK_PATH,
    generate_demand,
    initial_exclusion_limitation,
)
from backend.simulation.ai_fixed_run import (
    DEFAULT_MAX_SIMULATION_TIME_S,
    DEFAULT_TELEPORT_THRESHOLD_S,
    STEP_LENGTH_S,
    read_event_totals,
    read_fixed_program,
    read_planned_demand,
    read_tripinfo,
    write_runtime_config,
)
from backend.simulation.ai_input import JsonlValidationError
from backend.simulation.replay import ReplayWriter
from backend.simulation.runner import DEFAULT_MAPPING_PATH, SumoRunner


ADAPTIVE_STRATEGIES = ("legacy", "gap_v1")
DEFAULT_GAP_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "scenarios"
    / "single_intersection"
    / "gap_v1.experimental.json"
)
PHASE_ORDER = (
    "north_south_green",
    "north_south_yellow",
    "all_red_after_north_south",
    "east_west_green",
    "east_west_yellow",
    "all_red_after_east_west",
)
GREEN_PHASES = {0, 3}
YELLOW_PHASES = {1, 4}
ALL_RED_PHASES = {2, 5}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_adaptive_manifest(
    adaptive_strategy: str,
    adaptive_manifest_path: Path | None,
) -> Path | None:
    """Resolve explicit gap control without changing the legacy default."""
    if adaptive_strategy not in ADAPTIVE_STRATEGIES:
        raise ValueError(f"unsupported adaptive strategy {adaptive_strategy!r}")
    if adaptive_strategy == "legacy":
        if adaptive_manifest_path is not None:
            raise ValueError("legacy adaptive does not accept an adaptive manifest")
        return None
    path = (adaptive_manifest_path or DEFAULT_GAP_MANIFEST_PATH).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"gap_v1 adaptive manifest not found: {path}")
    return path


def validate_phase_transitions(
    transitions: list[dict[str, Any]],
) -> list[str]:
    """Validate complete observed intervals without changing SUMO's phase plan."""
    errors: list[str] = []
    for current, following in zip(transitions, transitions[1:]):
        phase_index = int(current["phase_index"])
        next_index = int(following["phase_index"])
        began = float(current["simulation_time_s"])
        ended = float(following["simulation_time_s"])
        duration = ended - began
        if not 0 <= phase_index < len(PHASE_ORDER):
            errors.append(f"unknown phase index {phase_index} at {began:g}s")
            continue
        if current["phase_id"] != PHASE_ORDER[phase_index]:
            errors.append(
                f"phase {phase_index} has unexpected name {current['phase_id']!r}"
            )
        expected_next = (phase_index + 1) % len(PHASE_ORDER)
        if next_index != expected_next:
            errors.append(
                f"unsafe phase order at {ended:g}s: {phase_index} -> {next_index}"
            )
            continue
        if phase_index in GREEN_PHASES and not 10.0 <= duration <= 46.0:
            errors.append(f"green phase {phase_index} lasted {duration:g}s")
        elif phase_index in YELLOW_PHASES and duration != 3.0:
            errors.append(f"yellow phase {phase_index} lasted {duration:g}s")
        elif phase_index in ALL_RED_PHASES and duration != 2.0:
            errors.append(f"all-red phase {phase_index} lasted {duration:g}s")
    return errors


def compare_fixed_demand(adaptive_route: Path, fixed_route: Path) -> dict[str, Any]:
    """Compare deterministic planned IDs/timestamps with an optional fixed run."""
    adaptive = read_planned_demand(adaptive_route)
    fixed = read_planned_demand(fixed_route)
    return {
        "checked": True,
        "fixed_route": str(fixed_route.resolve()),
        "ids_match": set(adaptive) == set(fixed),
        "planned_departures_match": adaptive == fixed,
        "route_file_sha256_match": _sha256(adaptive_route) == _sha256(fixed_route),
    }


def run_adaptive_experiment(
    counts_path: Path,
    events_path: Path,
    output_directory: Path,
    *,
    network_path: Path = DEFAULT_NETWORK_PATH,
    mapping_path: Path = DEFAULT_MAPPING_PATH,
    sumo_binary: str = "sumo",
    max_simulation_time_s: float = DEFAULT_MAX_SIMULATION_TIME_S,
    wall_timeout_s: float = 120.0,
    step_delay_ms: float = 0.0,
    fixed_demand_route: Path | None = None,
    adaptive_strategy: str = "legacy",
    adaptive_manifest_path: Path | None = None,
    replay_output_path: Path | None = None,
    overwrite: bool = False,
    allow_unknown_initial_observations: bool = False,
) -> dict[str, Any]:
    """Generate identical demand, apply existing adaptive control, and account trips."""
    if max_simulation_time_s <= 264:
        raise ValueError("max simulation time must extend beyond the 264-second recording")
    if wall_timeout_s <= 0 or step_delay_ms < 0:
        raise ValueError("wall timeout must be positive and step delay nonnegative")
    resolved_manifest = resolve_adaptive_manifest(
        adaptive_strategy, adaptive_manifest_path
    )

    output_directory = output_directory.resolve()
    paths = {
        "routes": output_directory / "ai_demand.rou.xml",
        "demand_summary": output_directory / "ai_demand.summary.json",
        "config": output_directory / "adaptive_runtime.sumocfg",
        "tripinfo": output_directory / "tripinfo.xml",
        "summary": output_directory / "summary.xml",
        "collisions": output_directory / "collisions.xml",
        "stderr": output_directory / "sumo_traci.stderr.log",
        "accounting": output_directory / "insertion_accounting.jsonl",
        "transitions": output_directory / "phase_transitions.json",
        "report": output_directory / "adaptive_run_summary.json",
    }
    existing = [path for path in paths.values() if path.exists()]
    if replay_output_path is not None and replay_output_path.resolve().exists():
        existing.append(replay_output_path.resolve())
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
        allow_unknown_initial_observations=allow_unknown_initial_observations,
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
    planned = read_planned_demand(paths["routes"])
    fixed_comparison: dict[str, Any] = {"checked": False}
    if fixed_demand_route is not None:
        fixed_comparison = compare_fixed_demand(paths["routes"], fixed_demand_route)

    runner = SumoRunner(
        config_path=paths["config"],
        mapping_path=mapping_path,
        sumo_binary=sumo_binary,
        run_id="ai-demand-adaptive",
        control_mode="adaptive",
        output_directory=output_directory,
        adaptive_manifest_path=resolved_manifest,
    )
    controller_provenance: dict[str, Any] = {
        "selected_strategy": adaptive_strategy,
        "profile_id": (
            "legacy_synthetic_adaptive"
            if resolved_manifest is None
            else None
        ),
        "manifest_path": str(resolved_manifest) if resolved_manifest else None,
        "manifest_sha256": _sha256(resolved_manifest) if resolved_manifest else None,
        "active_traffic_light_ids": [],
        "active_strategies": [],
        "active_strategy_verified_at_runtime": False,
        "gap_release_decision_count": 0,
        "validation_errors": [],
    }
    transitions: list[dict[str, Any]] = []
    departed = arrived = collision_vehicle_events = teleports = 0
    timed_out = False
    pending_at_stop = True
    run_error: str | None = None
    replay_writer = ReplayWriter(replay_output_path) if replay_output_path else None
    started_at = time.monotonic()
    with paths["stderr"].open("w", encoding="utf-8") as stderr_log:
        try:
            with contextlib.redirect_stderr(stderr_log):
                runner.start()
                snapshot = runner.extract_snapshot()
                if replay_writer is not None:
                    replay_writer.write_snapshot(snapshot)
                if adaptive_strategy == "gap_v1":
                    adaptive = snapshot.get("adaptive_control")
                    active_ids = (
                        list(adaptive.get("traffic_light_ids", []))
                        if isinstance(adaptive, dict)
                        else []
                    )
                    active_strategies = [
                        signal.strategy for signal in runner._adaptive_signals
                    ]
                    controller_provenance.update({
                        "profile_id": (
                            adaptive.get("scope")
                            if isinstance(adaptive, dict)
                            else None
                        ),
                        "active_traffic_light_ids": active_ids,
                        "active_strategies": active_strategies,
                    })
                    if active_ids != ["demo_01"]:
                        raise ValueError(
                            "gap_v1 manifest did not activate only demo_01"
                        )
                    if active_strategies != ["gap_v1"]:
                        raise ValueError(
                            "gap_v1 manifest did not activate the gap_v1 strategy"
                        )
                    controller_provenance[
                        "active_strategy_verified_at_runtime"
                    ] = True
                else:
                    if snapshot.get("adaptive_control") is not None:
                        raise ValueError(
                            "legacy adaptive unexpectedly activated a manifest controller"
                        )
                    if snapshot["traffic_light_id"] != "demo_01":
                        raise ValueError(
                            "legacy adaptive did not activate the demo_01 controller"
                        )
                    controller_provenance.update({
                        "active_traffic_light_ids": [snapshot["traffic_light_id"]],
                        "active_strategies": ["legacy"],
                        "active_strategy_verified_at_runtime": True,
                    })
                last_phase = int(snapshot["current_phase_index"])
                transitions.append({
                    "simulation_time_s": float(snapshot["simulation_time_s"]),
                    "phase_index": last_phase,
                    "phase_id": snapshot["current_phase_id"],
                })
                while (
                    runner.has_pending_vehicles()
                    and float(runner.connection.simulation.getTime()) < max_simulation_time_s
                ):
                    if time.monotonic() - started_at > wall_timeout_s:
                        timed_out = True
                        break
                    previous_cycle_decision = runner.last_cycle_decision
                    runner.advance()
                    current_cycle_decision = runner.last_cycle_decision
                    if (
                        adaptive_strategy == "gap_v1"
                        and current_cycle_decision is not None
                        and current_cycle_decision is not previous_cycle_decision
                        and current_cycle_decision.get("reason")
                        == "green_gap_with_competing_demand"
                    ):
                        controller_provenance["gap_release_decision_count"] += 1
                    simulation = runner.connection.simulation
                    departed += int(simulation.getDepartedNumber())
                    arrived += int(simulation.getArrivedNumber())
                    collision_vehicle_events += int(
                        simulation.getCollidingVehiclesNumber()
                    )
                    teleports += int(simulation.getStartingTeleportNumber())
                    snapshot = runner.extract_snapshot()
                    if replay_writer is not None:
                        replay_writer.write_snapshot(snapshot)
                    phase = int(snapshot["current_phase_index"])
                    if phase != last_phase:
                        transitions.append({
                            "simulation_time_s": float(snapshot["simulation_time_s"]),
                            "phase_index": phase,
                            "phase_id": snapshot["current_phase_id"],
                        })
                        last_phase = phase
                    if step_delay_ms:
                        time.sleep(step_delay_ms / 1000.0)
                pending_at_stop = runner.has_pending_vehicles()
        except Exception as exc:  # Preserve diagnostics and return a failed report.
            run_error = f"{type(exc).__name__}: {exc}"
            controller_provenance["validation_errors"].append(run_error)
        finally:
            runner.close()
            if replay_writer is not None:
                replay_writer.close()

    paths["transitions"].write_text(
        json.dumps(transitions, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validation_errors: list[str] = []
    if run_error:
        validation_errors.append(f"TraCI run failed: {run_error}")
    if timed_out:
        validation_errors.append("adaptive run exceeded the wall-clock timeout")
    if pending_at_stop:
        validation_errors.append("vehicles remained at the simulation limit")

    records: list[dict[str, Any]] = []
    if paths["tripinfo"].is_file() and paths["summary"].is_file():
        records, trip_errors = read_tripinfo(paths["tripinfo"], planned)
        validation_errors.extend(trip_errors)
    else:
        validation_errors.append("SUMO did not produce tripinfo and summary outputs")
    record_by_id = {record["vehicle_id"]: record for record in records}
    inserted_ids = {
        vehicle_id for vehicle_id, record in record_by_id.items()
        if record["actual_depart_s"] is not None
    }
    arrived_ids = {
        vehicle_id for vehicle_id, record in record_by_id.items() if record["arrived"]
    }
    if inserted_ids != set(planned):
        validation_errors.append("inserted vehicle IDs differ from planned demand")
    if arrived_ids != set(planned):
        validation_errors.append("not every planned vehicle arrived")
    if fixed_comparison.get("checked") and not all(
        fixed_comparison[key]
        for key in ("ids_match", "planned_departures_match", "route_file_sha256_match")
    ):
        validation_errors.append("adaptive demand differs from the fixed baseline demand")

    summary_collision_events = summary_teleports = 0
    final_recorded_time: float | None = None
    if paths["summary"].is_file():
        summary_collision_events, summary_teleports, final_recorded_time = read_event_totals(
            paths["summary"]
        )
    collision_records = (
        len(list(ET.parse(paths["collisions"]).getroot().iter("collision")))
        if paths["collisions"].is_file()
        else 0
    )
    teleports = max(teleports, summary_teleports)
    if collision_records:
        validation_errors.append(f"SUMO reported {collision_records} collisions")
    if teleports:
        validation_errors.append(f"SUMO reported {teleports} teleports")

    phase_errors = validate_phase_transitions(transitions)
    validation_errors.extend(phase_errors)
    completed_phase_intervals = [
        (
            int(current["phase_index"]),
            float(following["simulation_time_s"])
            - float(current["simulation_time_s"]),
        )
        for current, following in zip(transitions, transitions[1:])
    ]
    observed_green_durations = [
        duration
        for phase_index, duration in completed_phase_intervals
        if phase_index in GREEN_PHASES
    ]
    delays = [
        float(record["insertion_delay_s"])
        for record in records if record["insertion_delay_s"] is not None
    ]
    for record in records:
        record["planned_to_final_arrival_s"] = (
            round(
                float(record["arrival_s"]) - float(record["planned_depart_s"]),
                6,
            )
            if record["arrival_s"] is not None
            else None
        )
    planned_to_arrival = [
        float(record["planned_to_final_arrival_s"])
        for record in records
        if record["planned_to_final_arrival_s"] is not None
    ]
    arrival_times = [
        float(record["arrival_s"])
        for record in records if record["arrival_s"] is not None
    ]
    actual_departures = [
        float(record["actual_depart_s"])
        for record in records if record["actual_depart_s"] is not None
    ]
    paths["accounting"].write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    trip_waiting_total = round(
        sum(float(item["waiting_time_s"]) for item in records), 3
    )
    replay_waiting_total = (
        replay_writer.final_cumulative_waiting_time_s
        if replay_writer is not None else None
    )
    waiting_reconciled = (
        replay_waiting_total is None
        or abs(replay_waiting_total - trip_waiting_total) <= 1e-6
    )
    if not waiting_reconciled:
        validation_errors.append(
            "replay cumulative waiting time differs from SUMO tripinfo"
        )

    report: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment": "ai_demand_single_intersection_adaptive",
        "control_mode": "adaptive",
        "controller": (
            "existing synthetic per-step adaptive controller"
            if adaptive_strategy == "legacy"
            else "gap_v1 via audited synthetic manifest"
        ),
        "controller_provenance": controller_provenance,
        "replay_export": replay_writer.summary() if replay_writer is not None else None,
        "replay_waiting_time_reconciliation": {
            "available": replay_waiting_total is not None,
            "replay_final_s": replay_waiting_total,
            "tripinfo_final_s": trip_waiting_total,
            "matches": waiting_reconciled,
        },
        "fixed_program": fixed_program,
        "validation": {
            "passed": not validation_errors,
            "errors": validation_errors,
            "traci_run_error": run_error,
            "wall_timeout_reached": timed_out,
            "maximum_simulation_time_s": max_simulation_time_s,
            "final_recorded_simulation_time_s": final_recorded_time,
            "phase_transition_errors": phase_errors,
        },
        "demand": demand_summary,
        "fixed_baseline_demand_comparison": fixed_comparison,
        "vehicles": {
            "planned": len(planned),
            "inserted": len(inserted_ids),
            "arrived": len(arrived_ids),
            "departed_events_observed": departed,
            "arrived_events_observed": arrived,
            "failed_insertions": len(set(planned) - inserted_ids),
            "unfinished": len(set(planned) - arrived_ids),
            "actual_departure_time_range_s": {
                "first": min(actual_departures, default=None),
                "last": max(actual_departures, default=None),
            },
            "all_completed_by_simulation_time_s": max(arrival_times, default=None),
        },
        "insertion_delay": {
            "definition": "actual SUMO depart minus planned AI video timestamp",
            "vehicles_with_any_delay": sum(delay > 1e-6 for delay in delays),
            "vehicles_delayed_beyond_one_simulation_step": sum(
                delay > STEP_LENGTH_S + 1e-6 for delay in delays
            ),
            "total_delay_s": round(sum(delays), 3),
            "average_delay_s": round(sum(delays) / len(delays), 3) if delays else None,
            "maximum_delay_s": round(max(delays), 3) if delays else None,
            "simulation_step_s": STEP_LENGTH_S,
        },
        "trip_metrics": {
            "scope": "all completed vehicles" if arrived_ids == set(planned) else "available tripinfo records",
            "total_waiting_time_s": trip_waiting_total,
            "average_waiting_time_s": (
                round(sum(float(item["waiting_time_s"]) for item in records) / len(records), 3)
                if records else None
            ),
            "total_time_loss_s": round(sum(float(item["time_loss_s"]) for item in records), 3),
            "average_time_loss_s": (
                round(sum(float(item["time_loss_s"]) for item in records) / len(records), 3)
                if records else None
            ),
            "planned_to_final_arrival": {
                "definition": "SUMO arrival time minus AI planned departure time",
                "total_duration_s": round(sum(planned_to_arrival), 3),
                "average_duration_s": (
                    round(sum(planned_to_arrival) / len(planned_to_arrival), 3)
                    if planned_to_arrival else None
                ),
                "maximum_duration_s": (
                    round(max(planned_to_arrival), 3) if planned_to_arrival else None
                ),
            },
        },
        "signal_safety": {
            "phase_transitions_observed": len(transitions),
            "phase_order": list(PHASE_ORDER),
            "green_bounds_s": {
                "configured_minimum": 10.0,
                "configured_maximum": 45.0,
                "observed_minimum": min(observed_green_durations, default=None),
                "observed_maximum": max(observed_green_durations, default=None),
                "completed_interval_validation_maximum": 46.0,
            },
            "yellow_duration_s": 3.0,
            "all_red_duration_s": 2.0,
            "errors": phase_errors,
        },
        "diagnostics": {
            "collisions": collision_records,
            "collision_involved_vehicle_events": max(
                collision_vehicle_events, summary_collision_events
            ),
            "teleports": teleports,
            "teleport_threshold_s": DEFAULT_TELEPORT_THRESHOLD_S,
        },
        "limitations": [
            initial_exclusion_limitation(
                demand_summary,
                "The {count} vehicles already observed at video t=0 are excluded; their positions are unknown.",
            ),
            "Camera-to-SUMO orientation is unverified.",
            "All generated movements are straight-only verified synthetic connections.",
            "AI intersection entry/exit times do not command or remove SUMO vehicles.",
            "This recorded-video experiment does not establish real-world traffic savings.",
        ],
    }
    paths["report"].write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK_PATH)
    parser.add_argument("--mappings", type=Path, default=DEFAULT_MAPPING_PATH)
    parser.add_argument("--sumo-binary", default="sumo")
    parser.add_argument("--max-simulation-time", type=float, default=DEFAULT_MAX_SIMULATION_TIME_S)
    parser.add_argument("--wall-timeout", type=float, default=120.0)
    parser.add_argument("--step-delay-ms", type=float, default=0.0)
    parser.add_argument("--fixed-demand-route", type=Path)
    parser.add_argument(
        "--adaptive-strategy",
        choices=ADAPTIVE_STRATEGIES,
        default="legacy",
        help="legacy is the unchanged default; gap_v1 is explicit experimental opt-in",
    )
    parser.add_argument(
        "--adaptive-manifest",
        type=Path,
        help="gap_v1 manifest override; valid only with --adaptive-strategy gap_v1",
    )
    parser.add_argument(
        "--replay-output",
        type=Path,
        help="optional JSONL trajectory export; existing files are never overwritten",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--allow-unknown-initial-observations",
        action="store_true",
        help="accept a t_s=0 count snapshot without arm data; those counts are recorded as unknown",
    )
    args = parser.parse_args()
    try:
        report = run_adaptive_experiment(
            args.counts,
            args.events,
            args.output_directory,
            network_path=args.network,
            mapping_path=args.mappings,
            sumo_binary=args.sumo_binary,
            max_simulation_time_s=args.max_simulation_time,
            wall_timeout_s=args.wall_timeout,
            step_delay_ms=args.step_delay_ms,
            fixed_demand_route=args.fixed_demand_route,
            adaptive_strategy=args.adaptive_strategy,
            adaptive_manifest_path=args.adaptive_manifest,
            replay_output_path=args.replay_output,
            overwrite=args.overwrite,
            allow_unknown_initial_observations=args.allow_unknown_initial_observations,
        )
    except (FileExistsError, FileNotFoundError, JsonlValidationError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
