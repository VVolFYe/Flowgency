"""Validate London network connectivity and candidate mapping identifiers."""

from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

SCENARIO_DIR = Path(__file__).resolve().parent
SUMO_TOOLS = Path(os.environ.get("SUMO_HOME", "/usr/share/sumo")) / "tools"
if str(SUMO_TOOLS) not in sys.path:
    sys.path.insert(0, str(SUMO_TOOLS))

import sumolib  # type: ignore[import-not-found]  # noqa: E402


def main() -> int:
    network_path = SCENARIO_DIR / "london.net.xml"
    mappings_path = SCENARIO_DIR / "mapping_candidates.json"
    network = sumolib.net.readNet(str(network_path), withInternal=True)
    root = ET.parse(network_path).getroot()
    with mappings_path.open(encoding="utf-8") as source:
        mappings = json.load(source)

    external_edges = [edge for edge in network.getEdges() if edge.getFunction() != "internal"]
    internal_edges = [edge for edge in network.getEdges() if edge.getFunction() == "internal"]
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in external_edges:
        start = edge.getFromNode().getID()
        end = edge.getToNode().getID()
        adjacency[start].add(end)
        adjacency[end].add(start)

    seen: set[str] = set()
    components = []
    for start in adjacency:
        if start in seen:
            continue
        pending = [start]
        seen.add(start)
        component = set()
        while pending:
            node = pending.pop()
            component.add(node)
            for neighbor in adjacency[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    pending.append(neighbor)
        components.append(component)

    junction_ids = {node.getID() for node in network.getNodes()}
    traffic_light_ids = {tls.getID() for tls in network.getTrafficLights()}
    edge_ids = {edge.getID() for edge in external_edges}
    errors = []
    for target in mappings["targets"]:
        for candidate in target["candidates"]:
            if candidate["junction_id"] not in junction_ids:
                errors.append(f"{target['intersection_id']}: missing junction {candidate['junction_id']}")
            if candidate["traffic_light_id"] not in traffic_light_ids:
                errors.append(
                    f"{target['intersection_id']}: missing TLS {candidate['traffic_light_id']}"
                )
            for edge_id in candidate["incoming_edges"]:
                if edge_id not in edge_ids:
                    errors.append(f"{target['intersection_id']}: missing edge {edge_id}")

    result = {
        "left_hand_traffic": root.get("lefthand") == "true",
        "junctions": len(network.getNodes()),
        "external_edges": len(external_edges),
        "internal_edges": len(internal_edges),
        "external_lanes": sum(len(edge.getLanes()) for edge in external_edges),
        "internal_lanes": sum(len(edge.getLanes()) for edge in internal_edges),
        "traffic_lights": len(network.getTrafficLights()),
        "weak_components": len(components),
        "mapping_candidates_valid": not errors,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["left_hand_traffic"] and len(components) == 1 and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
