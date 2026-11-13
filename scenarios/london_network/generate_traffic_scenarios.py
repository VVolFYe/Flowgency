#!/usr/bin/env python3
"""Generate deterministic, target-covering London traffic demand profiles."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET


SCENARIO_DIR = Path(__file__).resolve().parent
NET_FILE = SCENARIO_DIR / "london.net.xml"
MAPPINGS_FILE = SCENARIO_DIR / "mapping_candidates.json"
DEMAND_DIR = SCENARIO_DIR / "demand"
CONFIG_DIR = SCENARIO_DIR / "configs"
SEED = 20261113
DEPARTURE_WINDOW_SECONDS = 900.0
SIMULATION_END_SECONDS = 2400.0

PROFILE_COUNTS = {
    "normal": {"default": 20},
    "rush_hour": {"default": 30},
    "unbalanced": {
        "default": 8,
        "overrides": {
            "-1015085160#0": 180,  # Vassall Road at J3
            "-5001019#4": 180,     # Caldwell Street at J3
            "-66924592#2": 8,      # Brixton Road at J3
            "1118018433#0": 8,     # Brixton Road at J3
        },
    },
}


def load_sumolib():
    try:
        import sumolib  # type: ignore
    except ImportError:
        tools = os.environ.get("SUMO_HOME")
        if tools:
            sys.path.append(str(Path(tools) / "tools"))
        else:
            sys.path.append("/usr/share/sumo/tools")
        import sumolib  # type: ignore
    return sumolib


@dataclass(frozen=True)
class Approach:
    target_id: str
    edge_id: str


def load_approaches() -> list[Approach]:
    data = json.loads(MAPPINGS_FILE.read_text(encoding="utf-8"))
    approaches: list[Approach] = []
    seen: set[str] = set()
    for target in data["targets"]:
        for candidate in target["candidates"]:
            for edge_id in candidate["incoming_edges"]:
                if edge_id not in seen:
                    approaches.append(Approach(target["intersection_id"], edge_id))
                    seen.add(edge_id)
    return approaches


def edge_midpoint(edge) -> tuple[float, float]:
    shape = edge.getShape()
    first, last = shape[0], shape[-1]
    return ((first[0] + last[0]) / 2, (first[1] + last[1]) / 2)


def find_route_through(net, target, usable_edges) -> tuple[str, ...]:
    tx, ty = edge_midpoint(target)
    ranked = sorted(
        usable_edges,
        key=lambda edge: (
            abs(math.dist((tx, ty), edge_midpoint(edge)) - 650.0),
            edge.getID(),
        ),
    )

    prefixes = []
    for edge in ranked:
        if edge == target:
            continue
        path, cost = net.getShortestPath(edge, target, vClass="passenger")
        if path and 100 <= cost <= 1300 and len({item.getID() for item in path}) == len(path):
            prefixes.append(path)
            if len(prefixes) == 20:
                break
    # A bounded OSM extract can leave an incoming edge without a routable
    # passenger predecessor. Starting on that edge still exercises its stop line.
    if not prefixes:
        prefixes = [(target,)]

    prefix = suffix = None
    for edge in ranked:
        if edge == target:
            continue
        path, cost = net.getShortestPath(target, edge, vClass="passenger")
        if path and 100 <= cost <= 1300 and len({item.getID() for item in path}) == len(path):
            suffix_ids = {item.getID() for item in path[1:]}
            for candidate in prefixes:
                if not suffix_ids.intersection(item.getID() for item in candidate):
                    prefix, suffix = candidate, path
                    break
            if suffix is not None:
                break
    if suffix is None:
        # Preserve coverage evidence for mapped dead ends while making the
        # network defect explicit in the generated route (it ends here).
        prefix = prefixes[0]
        suffix = (target,)

    return tuple(edge.getID() for edge in (*prefix, *suffix[1:]))


def write_routes(profile: str, templates: dict[str, tuple[str, ...]], approaches: list[Approach]) -> int:
    settings = PROFILE_COUNTS[profile]
    overrides = settings.get("overrides", {})
    vehicles: list[tuple[float, str, tuple[str, ...]]] = []
    for approach_index, approach in enumerate(approaches):
        count = overrides.get(approach.edge_id, settings["default"])
        rng = random.Random(f"{SEED}:{profile}:{approach.edge_id}")
        for index in range(count):
            base = (index + 0.5) * DEPARTURE_WINDOW_SECONDS / count
            jitter = rng.uniform(-0.35, 0.35) * DEPARTURE_WINDOW_SECONDS / count
            depart = max(0.0, min(DEPARTURE_WINDOW_SECONDS - 0.01, base + jitter))
            vehicle_id = f"{profile}.{approach.target_id}.{approach_index:02d}.{index:04d}"
            vehicles.append((depart, vehicle_id, templates[approach.edge_id]))
    vehicles.sort(key=lambda item: (item[0], item[1]))

    root = ET.Element("routes", {
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:noNamespaceSchemaLocation": "https://sumo.dlr.de/xsd/routes_file.xsd",
    })
    ET.SubElement(root, "vType", {
        "id": "passenger_deterministic", "vClass": "passenger",
        "length": "5.0", "minGap": "2.5", "accel": "2.6", "decel": "4.5",
        "sigma": "0", "speedFactor": "1", "speedDev": "0",
    })
    for depart, vehicle_id, route in vehicles:
        vehicle = ET.SubElement(root, "vehicle", {
            "id": vehicle_id, "type": "passenger_deterministic",
            "depart": f"{depart:.2f}", "departLane": "best", "departSpeed": "max",
        })
        ET.SubElement(vehicle, "route", {"edges": " ".join(route)})

    ET.indent(root, space="    ")
    output = DEMAND_DIR / f"{profile}.rou.xml"
    ET.ElementTree(root).write(output, encoding="UTF-8", xml_declaration=True)
    return len(vehicles)


def write_config(profile: str) -> None:
    content = f'''<?xml version="1.0" encoding="UTF-8"?>
<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xsi:noNamespaceSchemaLocation="https://sumo.dlr.de/xsd/sumoConfiguration.xsd">
    <input>
        <net-file value="../london.net.xml"/>
        <route-files value="../demand/{profile}.rou.xml"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="{SIMULATION_END_SECONDS:.0f}"/>
        <step-length value="1"/>
    </time>
    <random_number><seed value="{SEED}"/></random_number>
    <output>
        <tripinfo-output value="../output/{profile}/tripinfo.xml"/>
        <tripinfo-output.write-unfinished value="true"/>
        <summary-output value="../output/{profile}/summary.xml"/>
        <summary-output.period value="10"/>
    </output>
    <processing>
        <collision.action value="warn"/>
        <collision.check-junctions value="true"/>
    </processing>
    <report><verbose value="true"/><no-step-log value="true"/></report>
</configuration>
'''
    (CONFIG_DIR / f"{profile}.sumocfg").write_text(content, encoding="utf-8")


def generate() -> None:
    sumolib = load_sumolib()
    net = sumolib.net.readNet(str(NET_FILE), withInternal=True)
    approaches = load_approaches()
    usable_edges = [
        edge for edge in net.getEdges(withInternal=False)
        if edge.allows("passenger") and edge.getFunction() == ""
    ]
    templates = {
        approach.edge_id: find_route_through(net, net.getEdge(approach.edge_id), usable_edges)
        for approach in approaches
    }
    DEMAND_DIR.mkdir(exist_ok=True)
    CONFIG_DIR.mkdir(exist_ok=True)
    for profile in PROFILE_COUNTS:
        count = write_routes(profile, templates, approaches)
        write_config(profile)
        print(f"generated {profile}: {count} vehicles, {len(templates)} covered approaches")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    generate()
