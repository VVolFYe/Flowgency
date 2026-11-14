"""Compare fixed and adaptive control on identical synthetic SUMO demand."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from .runner import DEFAULT_MAPPING_PATH, DEFAULT_SCENARIO_DIRECTORY, SumoRunner

PHASES = (
    "north_south_green", "north_south_yellow", "all_red_after_north_south",
    "east_west_green", "east_west_yellow", "all_red_after_east_west",
)
GREEN = {PHASES[0], PHASES[3]}


def validate_phases(changes: list[tuple[float, str]], mode: str) -> list[str]:
    """Check complete intervals; the final truncated phase has no known end."""
    errors: list[str] = []
    for interval, ((began, phase), (ended, following)) in enumerate(zip(changes, changes[1:])):
        if phase not in PHASES or following != PHASES[(PHASES.index(phase) + 1) % len(PHASES)]:
            errors.append(f"unsafe phase order at {ended}: {phase} -> {following}")
            continue
        duration = ended - began
        if phase in GREEN:
            low, high = (30, 30) if mode == "fixed" else (10, 46)
            if mode == "fixed" and interval == 0 and began == 0 and phase == PHASES[0]:
                # SUMO 1.18 reports the initial switch after step 31; later
                # fixed greens must still be exactly the configured 30 s.
                high = 31
        elif "yellow" in phase:
            low = high = 3
        else:
            low = high = 2
        if not low <= duration <= high:
            errors.append(f"invalid {phase} duration {duration:g}s (expected {low}-{high}s)")
    return errors


def trip_metrics(path: Path) -> dict[str, float | int]:
    root = ET.parse(path).getroot()
    trips = root.findall("tripinfo")
    completed = [trip for trip in trips if float(trip.get("arrival", "-1")) >= 0]
    waits = [float(trip.get("waitingTime", "0")) for trip in completed]
    return {
        "completed_trips": len(completed),
        "unfinished_trips": len(trips) - len(completed),
        "average_waiting_time_s": round(sum(waits) / len(waits), 3) if waits else 0.0,
        "total_waiting_time_s": round(sum(waits), 3),
    }


def run_mode(config: Path, mode: str, binary: str) -> dict:
    runner = SumoRunner(config, DEFAULT_MAPPING_PATH, sumo_binary=binary, control_mode=mode)
    changes: list[tuple[float, str]] = []
    queue_total = queue_max = samples = departed = arrived = collisions = teleports = 0
    with runner:
        initial = runner.extract_snapshot()
        changes.append((initial["simulation_time_s"], initial["current_phase_id"]))
        while runner.has_pending_vehicles():
            runner.advance()
            snapshot = runner.extract_snapshot()
            phase = snapshot["current_phase_id"]
            if not changes or phase != changes[-1][1]:
                changes.append((snapshot["simulation_time_s"], phase))
            queue = sum(item["vehicles"] for item in snapshot["queue_lengths_by_approach"].values())
            queue_total += queue
            queue_max = max(queue_max, queue)
            samples += 1
            simulation = runner.connection.simulation
            departed += int(simulation.getDepartedNumber())
            arrived += int(simulation.getArrivedNumber())
            collisions += int(simulation.getCollidingVehiclesNumber())
            teleports += int(simulation.getStartingTeleportNumber())

    output = config.parent / "output" / "tripinfo.xml"
    metrics = trip_metrics(output)
    errors = validate_phases(changes, mode)
    if collisions or teleports or metrics["unfinished_trips"] or arrived != departed:
        errors.append("run has collisions, teleports, unfinished trips, or unmatched departures")
    return {
        "control_mode": mode,
        "departed_vehicles": departed,
        "arrived_vehicles": arrived,
        "collisions": collisions,
        "teleports": teleports,
        "mean_queue_vehicles": round(queue_total / samples, 3) if samples else 0.0,
        "max_queue_vehicles": queue_max,
        "observed_phase_changes": len(changes),
        "phase_errors": errors,
        **metrics,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("demo", "peak"), default="peak")
    parser.add_argument("--sumo-binary", default="sumo")
    args = parser.parse_args()
    config = DEFAULT_SCENARIO_DIRECTORY / f"{args.scenario}.sumocfg"
    fixed = run_mode(config, "fixed", args.sumo_binary)
    adaptive = run_mode(config, "adaptive", args.sumo_binary)
    print(json.dumps({"scenario": args.scenario, "fixed": fixed, "adaptive": adaptive}, indent=2))
    return 0 if not fixed["phase_errors"] and not adaptive["phase_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
