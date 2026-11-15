"""Generate deterministic offline SUMO demand from AI approach-arrival events."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from backend.models.gates import GateEventInput
from backend.simulation.ai_input import (
    DEFAULT_MAPPING_PATH,
    DEFAULT_SCENARIO_MAPPING_PATH,
    JsonlValidationError,
    build_timeline,
    read_jsonl,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NETWORK_PATH = (
    REPOSITORY_ROOT / "scenarios" / "single_intersection" / "demo.net.xml"
)
ARM_ORDER = {arm: index for index, arm in enumerate(("north", "east", "south", "west"))}


@dataclass(frozen=True)
class StraightRoute:
    camera_arm: str
    route_id: str
    incoming_edge_id: str
    outgoing_edge_id: str


@dataclass(frozen=True)
class Arrival:
    vehicle_id: str
    camera_arm: str
    track_id: int
    depart_s: float
    route_id: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _format_seconds(value: float) -> str:
    return format(value, ".15g")


def initial_vehicles_excluded(demand_summary: dict[str, Any]) -> int | None:
    """Return the known count of vehicles visible at t=0 (never inserted), else None."""
    initial = demand_summary.get("initial_observed_vehicles_not_inserted")
    total = initial.get("total") if isinstance(initial, dict) else None
    return total if type(total) is int else None


def initial_exclusion_limitation(demand_summary: dict[str, Any], template: str) -> str:
    """Describe the excluded starting vehicles from real data.

    ``template`` uses ``{count}`` and ``{at}`` (e.g. ``"... at video {at} ..."``);
    ``{at}`` is ``t=0`` or the later warm-up line where counts first became known.
    An unknown count is never invented.
    """
    count = initial_vehicles_excluded(demand_summary)
    if count is not None:
        initial = demand_summary.get("initial_observed_vehicles_not_inserted", {})
        observed_at = initial.get("observed_at_t_s") if isinstance(initial, dict) else None
        at = (
            "t=0"
            if not isinstance(observed_at, (int, float)) or observed_at == 0
            else f"t={observed_at:g}s (first counts line with every arm known)"
        )
        return template.format(count=count, at=at)
    if isinstance(initial := demand_summary.get("initial_observed_vehicles_not_inserted"), dict) and (
        initial.get("status") == "unknown_at_t0"
    ):
        # Summaries written before the warm-up rule was merged recorded only the unknown t=0 line.
        return "Approach vehicles present at video t=0 were not observed (count unknown) and are not inserted."
    return (
        "Starting approach vehicles were not observed on any complete counts line "
        "(count unknown) and are not inserted."
    )


def derive_straight_routes(
    network_path: Path,
    arm_mapping: dict[str, Any],
    scenario_mapping_path: Path = DEFAULT_SCENARIO_MAPPING_PATH,
) -> dict[str, StraightRoute]:
    """Derive one controlled straight movement for every configured camera arm."""
    try:
        network = ET.parse(network_path).getroot()
        scenario = json.loads(scenario_mapping_path.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError, json.JSONDecodeError) as exc:
        raise JsonlValidationError(f"could not load synthetic network mappings: {exc}") from exc

    edge_ids = {
        edge.get("id") for edge in network.findall("edge")
        if edge.get("id") and not edge.get("id", "").startswith(":")
    }
    controlled_pairs = {
        (
            str(link.get("from_lane", "")).rsplit("_", 1)[0],
            str(link.get("to_lane", "")).rsplit("_", 1)[0],
        )
        for link in scenario.get("controlled_links", [])
        if link.get("movement") == "straight"
    }
    routes: dict[str, StraightRoute] = {}
    for arm, mapping in arm_mapping.items():
        incoming = mapping.sumo_incoming_edge_id
        candidates = {
            connection.get("to")
            for connection in network.findall("connection")
            if connection.get("from") == incoming
            and connection.get("dir", "").lower() == "s"
            and connection.get("to") in edge_ids
        }
        if len(candidates) != 1:
            raise JsonlValidationError(
                f"camera arm {arm} incoming edge {incoming} has {len(candidates)} straight routes"
            )
        outgoing = next(iter(candidates))
        if incoming not in edge_ids or (incoming, outgoing) not in controlled_pairs:
            raise JsonlValidationError(
                f"straight route {incoming} -> {outgoing} is not in verified controlled links"
            )
        routes[arm] = StraightRoute(
            camera_arm=arm,
            route_id=f"ai_straight_{arm}",
            incoming_edge_id=incoming,
            outgoing_edge_id=outgoing,
        )
    return routes


def generate_demand(
    counts_path: Path,
    events_path: Path,
    output_path: Path,
    *,
    summary_path: Path | None = None,
    mapping_path: Path = DEFAULT_MAPPING_PATH,
    scenario_mapping_path: Path = DEFAULT_SCENARIO_MAPPING_PATH,
    network_path: Path = DEFAULT_NETWORK_PATH,
    overwrite: bool = False,
    allow_unknown_initial_observations: bool = False,
) -> dict[str, Any]:
    """Validate inputs and write one SUMO vehicle per unique approach arrival.

    The starting offset comes from the first counts line with every arm known
    (``timeline.initial_point``). ``allow_unknown_initial_observations`` is an
    explicit opt-in for recordings where no such line exists: the offset is then
    recorded as unknown (null), never as zero, and never creates vehicles.
    """
    if output_path.suffixes[-2:] != [".rou", ".xml"]:
        raise JsonlValidationError("output path must end with .rou.xml")
    summary_path = summary_path or output_path.with_suffix(".summary.json")
    for path in (output_path, summary_path):
        if path.exists() and not overwrite:
            raise FileExistsError(f"refusing to overwrite existing output: {path}")

    timeline = build_timeline(
        counts_path,
        events_path,
        mapping_path,
        scenario_mapping_path,
    )
    if timeline.points[0].t_s != 0:
        raise JsonlValidationError("counts input must include the initial t_s=0 observation")
    routes = derive_straight_routes(network_path, timeline.mapping, scenario_mapping_path)
    events = read_jsonl(events_path, GateEventInput)
    arrival_events = [event for event in events if event.event == "approach_entered"]
    arrivals = [
        Arrival(
            vehicle_id=f"ai_{event.arm}_{event.track_id}",
            camera_arm=event.arm,
            track_id=event.track_id,
            depart_s=event.t_s,
            route_id=routes[event.arm].route_id,
        )
        for event in arrival_events
    ]
    arrivals.sort(key=lambda item: (item.depart_s, ARM_ORDER[item.camera_arm], item.track_id))
    vehicle_ids = [item.vehicle_id for item in arrivals]
    if len(vehicle_ids) != len(set(vehicle_ids)):
        raise JsonlValidationError("arrival events produce duplicate SUMO vehicle IDs")
    timeline_arrival_count = sum(timeline.summary()["new_arrivals"].values())
    if len(arrivals) != timeline_arrival_count:
        raise JsonlValidationError("event arrivals do not match the validated timeline")

    root = ET.Element("routes", {
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:noNamespaceSchemaLocation": "https://sumo.dlr.de/xsd/routes_file.xsd",
    })
    ET.SubElement(root, "vType", {
        "id": "ai_passenger_deterministic",
        "vClass": "passenger",
        "length": "5.0",
        "minGap": "2.5",
        "accel": "2.6",
        "decel": "4.5",
        "sigma": "0",
        "speedFactor": "1",
        "speedDev": "0",
    })
    for arm in ARM_ORDER:
        route = routes[arm]
        ET.SubElement(root, "route", {
            "id": route.route_id,
            "edges": f"{route.incoming_edge_id} {route.outgoing_edge_id}",
        })
    for arrival in arrivals:
        ET.SubElement(root, "vehicle", {
            "id": arrival.vehicle_id,
            "type": "ai_passenger_deterministic",
            "route": arrival.route_id,
            "depart": _format_seconds(arrival.depart_s),
            "departLane": "best",
            "departSpeed": "max",
            "departPos": "base",
        })
    ET.indent(root, space="    ")

    # Starting offset: the first counts line with every mapped arm known (t_s=0 in older files,
    # the warm-up line since 2026-11-15). Those vehicles are metadata only and never inserted.
    initial_point = timeline.initial_point
    initial_unknown = initial_point is None
    if initial_unknown and not allow_unknown_initial_observations:
        raise JsonlValidationError(
            "no counts observation has the vehicle count known for every arm "
            "(pass --allow-unknown-initial-observations to record the starting offset as unknown)"
        )
    # Unknown stays unknown (null), never zero.
    initial = (
        {arm: state.observed_vehicles for arm, state in initial_point.approaches.items()}
        if initial_point is not None
        else {arm: None for arm in timeline.mapping}
    )
    arrivals_by_arm = Counter(item.camera_arm for item in arrivals)
    initial_total = None if initial_unknown else sum(
        value for value in initial.values() if value is not None
    )
    initial_assumption = (
        f"The {initial_total} initially observed approach vehicles are metadata only and are not inserted."
        if initial_total is not None
        else "No counts line had every arm known, so starting approach vehicles are unknown (not zero) and are not inserted."
    )
    summary: dict[str, Any] = {
        "schema_version": "1.0",
        "generator": "backend.simulation.ai_demand",
        "vehicle_count": len(arrivals),
        "arrival_time_range_s": {
            "first": arrivals[0].depart_s if arrivals else None,
            "last": arrivals[-1].depart_s if arrivals else None,
        },
        "arrivals_by_camera_arm": {
            arm: arrivals_by_arm.get(arm, 0) for arm in ARM_ORDER
        },
        "initial_observed_vehicles_not_inserted": {
            "observed_at_t_s": initial_point.t_s if initial_point is not None else None,
            "by_camera_arm": initial,
            "total": initial_total,
            **({"status": "unknown_no_complete_observation"} if initial_unknown else {}),
        },
        "camera_orientation_status": "unverified_camera_to_sumo",
        "routes": {
            arm: {
                "route_id": route.route_id,
                "incoming_edge_id": route.incoming_edge_id,
                "outgoing_edge_id": route.outgoing_edge_id,
                "movement": "straight",
            }
            for arm, route in routes.items()
        },
        "ordering": "depart_s, camera_arm north/east/south/west, track_id",
        "assumptions": [
            "Only approach_entered events create SUMO vehicles.",
            "Each vehicle uses the verified straight-only movement for its mapped incoming edge.",
            initial_assumption,
            "Camera-arm orientation relative to the synthetic network is unverified.",
            "Optional future event fields, including emergency metadata, do not alter demand.",
        ],
        "sources": {
            "counts_sha256": _sha256(counts_path),
            "events_sha256": _sha256(events_path),
        },
    }
    if timeline.approach_left:
        # Reported for transparency only; approach_left never adds or removes vehicles.
        summary["approach_left_events_not_demand"] = {
            "count": len(timeline.approach_left),
            "by_camera_arm": {
                arm: sum(item.camera_arm == arm for item in timeline.approach_left)
                for arm in ARM_ORDER
            },
            "track_ids": [item.track_id for item in timeline.approach_left],
            "effect": "none; each track still has exactly one vehicle from its approach_entered event",
        }
        summary["assumptions"].append(
            "approach_left events are validated against their approach_entered event and do not change demand."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output_path, encoding="UTF-8", xml_declaration=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="destination .rou.xml")
    parser.add_argument("--summary-output", type=Path, help="default: <output>.summary.json")
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING_PATH)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK_PATH)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--allow-unknown-initial-observations",
        action="store_true",
        help="accept recordings where no counts line has every arm known; the starting offset is recorded as unknown",
    )
    args = parser.parse_args()
    try:
        summary = generate_demand(
            args.counts,
            args.events,
            args.output,
            summary_path=args.summary_output,
            mapping_path=args.mapping,
            network_path=args.network,
            overwrite=args.overwrite,
            allow_unknown_initial_observations=args.allow_unknown_initial_observations,
        )
    except (FileExistsError, FileNotFoundError, JsonlValidationError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
