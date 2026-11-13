"""Read and normalize static SUMO network geometry without using TraCI."""

from __future__ import annotations

import copy
import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

from .runner import DEFAULT_MAPPING_PATH, DEFAULT_SCENARIO_DIRECTORY

DEFAULT_NETWORK_PATH = DEFAULT_SCENARIO_DIRECTORY / "demo.net.xml"


def _import_sumolib() -> ModuleType:
    """Import the sumolib package bundled with the installed SUMO tools."""
    try:
        import sumolib  # type: ignore[import-not-found]

        return sumolib
    except ModuleNotFoundError:
        candidates = []
        if sumo_home := os.environ.get("SUMO_HOME"):
            candidates.append(Path(sumo_home) / "tools")
        candidates.extend((Path("/usr/share/sumo/tools"), Path("/usr/local/share/sumo/tools")))
        for tools_path in candidates:
            if (tools_path / "sumolib" / "__init__.py").is_file():
                sys.path.insert(0, str(tools_path))
                import sumolib  # type: ignore[import-not-found,no-redef]

                return sumolib
    raise RuntimeError(
        "sumolib was not found. Install SUMO tools or set SUMO_HOME to the SUMO root."
    )


def _point(xy: tuple[float, float]) -> dict[str, float]:
    return {"x_m": float(xy[0]), "y_m": float(xy[1])}


@lru_cache(maxsize=4)
def _load_cached(network_path: str, mapping_path: str) -> dict[str, Any]:
    """Parse immutable scenario sources once per process and path pair."""
    sumolib = _import_sumolib()
    network_file = Path(network_path)
    mapping_file = Path(mapping_path)
    if not network_file.is_file():
        raise FileNotFoundError(f"SUMO network not found: {network_file}")
    if not mapping_file.is_file():
        raise FileNotFoundError(f"SUMO mapping not found: {mapping_file}")

    with mapping_file.open(encoding="utf-8") as source:
        mapping = json.load(source)
    network = sumolib.net.readNet(str(network_file), withInternal=True)

    min_x, min_y, max_x, max_y = (float(value) for value in network.getBoundary())
    edges = []
    for edge in sorted(network.getEdges(withInternal=True), key=lambda item: item.getID()):
        is_internal = edge.getFunction() == "internal"
        lanes = []
        for lane in sorted(edge.getLanes(), key=lambda item: item.getIndex()):
            lanes.append(
                {
                    "lane_id": lane.getID(),
                    "index": int(lane.getIndex()),
                    "speed_limit_mps": float(lane.getSpeed()),
                    "length_m": float(lane.getLength()),
                    "width_m": float(lane.getWidth()),
                    "shape": [_point(point) for point in lane.getShape()],
                }
            )
        edges.append(
            {
                "edge_id": edge.getID(),
                "from_junction_id": edge.getFromNode().getID(),
                "to_junction_id": edge.getToNode().getID(),
                "function": edge.getFunction() or "normal",
                "is_internal": is_internal,
                "lanes": lanes,
            }
        )

    junctions = []
    for junction in sorted(network.getNodes(), key=lambda item: item.getID()):
        x_m, y_m = junction.getCoord()
        junctions.append(
            {
                "junction_id": junction.getID(),
                "type": junction.getType(),
                "x_m": float(x_m),
                "y_m": float(y_m),
                "shape": [_point(point) for point in junction.getShape()],
            }
        )

    traffic_lights = []
    actual_links: dict[str, set[tuple[int, str, str]]] = {}
    for traffic_light in sorted(network.getTrafficLights(), key=lambda item: item.getID()):
        links = {
            (int(link_index), from_lane.getID(), to_lane.getID())
            for from_lane, to_lane, link_index in traffic_light.getConnections()
        }
        actual_links[traffic_light.getID()] = links
        traffic_lights.append({"traffic_light_id": traffic_light.getID()})

    mapped_tls = mapping["sumo_traffic_light_id"]
    mapped_links = {
        (int(link["link_index"]), link["from_lane"], link["to_lane"])
        for link in mapping["controlled_links"]
    }
    if actual_links.get(mapped_tls) != mapped_links:
        raise ValueError(
            f"controlled links in {mapping_file} do not match traffic light {mapped_tls}"
        )

    return {
        "schema_version": "1.0",
        "scenario_id": mapping["scenario_id"],
        "coordinate_system": mapping["coordinate_system"],
        "bounds": {
            "min_x_m": min_x,
            "min_y_m": min_y,
            "max_x_m": max_x,
            "max_y_m": max_y,
        },
        "edges": edges,
        "junctions": junctions,
        "traffic_lights": traffic_lights,
        "controlled_links": copy.deepcopy(mapping["controlled_links"]),
    }


def get_network_geometry(
    network_path: Path = DEFAULT_NETWORK_PATH,
    mapping_path: Path = DEFAULT_MAPPING_PATH,
) -> dict[str, Any]:
    """Return a defensive copy of cached static geometry."""
    geometry = _load_cached(str(network_path.resolve()), str(mapping_path.resolve()))
    return copy.deepcopy(geometry)
