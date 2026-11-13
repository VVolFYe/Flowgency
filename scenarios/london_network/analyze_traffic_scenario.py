#!/usr/bin/env python3
"""Run one London demand profile and measure target coverage and queues."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET


SCENARIO_DIR = Path(__file__).resolve().parent
PROFILES = ("normal", "rush_hour", "unbalanced")


def load_traci():
    try:
        import traci  # type: ignore
    except ImportError:
        tools = Path(os.environ.get("SUMO_HOME", "/usr/share/sumo")) / "tools"
        sys.path.append(str(tools))
        import traci  # type: ignore
    return traci


def load_targets() -> tuple[dict[str, list[str]], list[str]]:
    data = json.loads((SCENARIO_DIR / "mapping_candidates.json").read_text(encoding="utf-8"))
    targets: dict[str, list[str]] = {}
    all_edges: list[str] = []
    for target in data["targets"]:
        edges = list(dict.fromkeys(
            edge
            for candidate in target["candidates"]
            for edge in candidate["incoming_edges"]
        ))
        targets[target["intersection_id"]] = edges
        all_edges.extend(edges)
    return targets, list(dict.fromkeys(all_edges))


def route_coverage(profile: str, targets: dict[str, list[str]]) -> tuple[int, dict[str, dict]]:
    root = ET.parse(SCENARIO_DIR / "demand" / f"{profile}.rou.xml").getroot()
    routes = [vehicle.find("route").get("edges", "").split() for vehicle in root.findall("vehicle")]
    coverage: dict[str, dict] = {}
    for target_id, edges in targets.items():
        per_edge = {edge: sum(edge in route for route in routes) for edge in edges}
        coverage[target_id] = {
            "vehicles_traversing_any_mapped_approach": sum(
                any(edge in route for edge in edges) for route in routes
            ),
            "vehicles_by_incoming_approach": per_edge,
        }
    return len(routes), coverage


def parse_tripinfo(path: Path) -> dict[str, float | int]:
    trips = ET.parse(path).getroot().findall("tripinfo")
    count = len(trips)
    def average(name: str) -> float:
        return round(sum(float(trip.get(name, "0")) for trip in trips) / count, 3) if count else 0.0
    return {
        "tripinfo_records": count,
        "average_duration_s": average("duration"),
        "average_waiting_time_s": average("waitingTime"),
        "average_time_loss_s": average("timeLoss"),
    }


def parse_summary(path: Path) -> dict[str, int]:
    final_step = ET.parse(path).getroot().findall("step")[-1]
    return {
        "collisions": int(final_step.get("collisions", "0")),
        "teleports": int(final_step.get("teleports", "0")),
    }


def run(profile: str) -> dict:
    traci = load_traci()
    targets, all_edges = load_targets()
    vehicle_count, coverage = route_coverage(profile, targets)
    output_dir = SCENARIO_DIR / "output" / profile
    output_dir.mkdir(parents=True, exist_ok=True)
    config = SCENARIO_DIR / "configs" / f"{profile}.sumocfg"

    queue_sum = defaultdict(float)
    queue_max = defaultdict(int)
    target_queue_max = defaultdict(int)
    steps = 0
    departed = arrived = collisions = teleports = 0
    final_time = 0.0
    traci.start(["sumo", "-c", str(config), "--no-warnings", "false"])
    try:
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            steps += 1
            final_time = float(traci.simulation.getTime())
            departed += int(traci.simulation.getDepartedNumber())
            arrived += int(traci.simulation.getArrivedNumber())
            collisions += int(traci.simulation.getCollidingVehiclesNumber())
            teleports += int(traci.simulation.getStartingTeleportNumber())
            for edge_id in all_edges:
                queued = int(traci.edge.getLastStepHaltingNumber(edge_id))
                queue_sum[edge_id] += queued
                queue_max[edge_id] = max(queue_max[edge_id], queued)
            for target_id, edges in targets.items():
                target_queue_max[target_id] = max(
                    target_queue_max[target_id],
                    sum(int(traci.edge.getLastStepHaltingNumber(edge)) for edge in edges),
                )
    finally:
        traci.close()

    for target_id, target in coverage.items():
        edges = targets[target_id]
        target["queue_by_incoming_approach"] = {
            edge: {
                "mean_vehicles": round(queue_sum[edge] / steps, 3) if steps else 0.0,
                "max_vehicles": queue_max[edge],
            }
            for edge in edges
        }
        target["max_total_queue_vehicles"] = target_queue_max[target_id]

    metrics = {
        "profile": profile,
        "seed": 20261113,
        "configured_vehicles": vehicle_count,
        "departed": departed,
        "arrived": arrived,
        "unfinished": max(0, departed - arrived),
        "simulation_end_s": final_time,
        "colliding_vehicle_observations": collisions,
        "teleports_started_observed": teleports,
        **parse_tripinfo(output_dir / "tripinfo.xml"),
        **parse_summary(output_dir / "summary.xml"),
        "target_coverage": coverage,
    }
    destination = output_dir / "metrics.generated.json"
    destination.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=PROFILES)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.profile), indent=2))
