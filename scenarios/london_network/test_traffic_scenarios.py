"""Lightweight consistency tests for generated London demand profiles."""

from __future__ import annotations

import json
import os
import random
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parent
EXPECTED_COUNTS = {"normal": 460, "rush_hour": 690, "unbalanced": 528}
SEED = 20261113
DEPARTURE_WINDOW_SECONDS = 900.0
PROFILE_COUNTS = {
    "normal": {"default": 20},
    "rush_hour": {"default": 30},
    "unbalanced": {
        "default": 8,
        "overrides": {
            "-1015085160#0": 180,
            "-5001019#4": 180,
            "-66924592#2": 8,
            "1118018433#0": 8,
        },
    },
}
J5_18_EDGE = "744514111#0"
J5_18_TLS = "GS_cluster_108195_6967968844"


def load_sumolib():
    try:
        import sumolib  # type: ignore
    except ImportError:
        tools = os.environ.get("SUMO_HOME")
        sys.path.append(str(Path(tools) / "tools") if tools else "/usr/share/sumo/tools")
        import sumolib  # type: ignore
    return sumolib


class TrafficScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        mappings = json.loads((ROOT / "mapping_candidates.json").read_text(encoding="utf-8"))
        cls.approaches = [
            (target["intersection_id"], edge)
            for target in mappings["targets"]
            for candidate in target["candidates"]
            for edge in candidate["incoming_edges"]
        ]
        cls.approaches = list(dict.fromkeys(cls.approaches))
        cls.mapped_edges = {edge for _, edge in cls.approaches}
        cls.net = load_sumolib().net.readNet(str(ROOT / "london.net.xml"), withInternal=True)

    def test_each_profile_has_expected_count_and_approach_coverage(self) -> None:
        self.assertEqual(len(self.mapped_edges), 23)
        for profile, expected in EXPECTED_COUNTS.items():
            root = ET.parse(ROOT / "demand" / f"{profile}.rou.xml").getroot()
            vehicles = root.findall("vehicle")
            self.assertEqual(len(vehicles), expected, profile)
            route_edges = {
                edge
                for vehicle in vehicles
                for edge in vehicle.find("route").get("edges", "").split()
            }
            self.assertTrue(self.mapped_edges.issubset(route_edges), profile)

            by_id = {vehicle.get("id"): vehicle for vehicle in vehicles}
            for approach_index, (target_id, edge_id) in enumerate(self.approaches):
                prefix = f"{profile}.{target_id}.{approach_index:02d}."
                selected = [vehicle for vehicle_id, vehicle in by_id.items() if vehicle_id.startswith(prefix)]
                expected = PROFILE_COUNTS[profile].get("overrides", {}).get(
                    edge_id, PROFILE_COUNTS[profile]["default"]
                )
                self.assertEqual(len(selected), expected, prefix)
                templates = {
                    tuple(vehicle.find("route").get("edges", "").split())
                    for vehicle in selected
                }
                self.assertEqual(len(templates), 1, prefix)
                self.assertIn(edge_id, next(iter(templates)), prefix)

    def test_departures_are_ordered_and_bounded(self) -> None:
        for profile in EXPECTED_COUNTS:
            vehicles = ET.parse(ROOT / "demand" / f"{profile}.rou.xml").getroot().findall("vehicle")
            departures = [float(vehicle.get("depart")) for vehicle in vehicles]
            self.assertEqual(departures, sorted(departures), profile)
            self.assertGreaterEqual(min(departures), 0)
            self.assertLess(max(departures), 900)

    def test_vehicle_ids_and_departures_match_deterministic_generation(self) -> None:
        for profile in EXPECTED_COUNTS:
            expected = []
            settings = PROFILE_COUNTS[profile]
            for approach_index, (target_id, edge_id) in enumerate(self.approaches):
                count = settings.get("overrides", {}).get(edge_id, settings["default"])
                rng = random.Random(f"{SEED}:{profile}:{edge_id}")
                for index in range(count):
                    base = (index + 0.5) * DEPARTURE_WINDOW_SECONDS / count
                    jitter = rng.uniform(-0.35, 0.35) * DEPARTURE_WINDOW_SECONDS / count
                    depart = max(0.0, min(DEPARTURE_WINDOW_SECONDS - 0.01, base + jitter))
                    expected.append((
                        depart,
                        f"{profile}.{target_id}.{approach_index:02d}.{index:04d}",
                    ))
            expected.sort(key=lambda item: (item[0], item[1]))
            expected_metadata = [(vehicle_id, f"{depart:.2f}") for depart, vehicle_id in expected]
            vehicles = ET.parse(ROOT / "demand" / f"{profile}.rou.xml").getroot().findall("vehicle")
            actual = [(vehicle.get("id"), vehicle.get("depart")) for vehicle in vehicles]
            self.assertEqual(actual, expected_metadata, profile)

    def test_unique_route_templates_are_continuous_and_passenger_legal(self) -> None:
        for profile in EXPECTED_COUNTS:
            vehicles = ET.parse(ROOT / "demand" / f"{profile}.rou.xml").getroot().findall("vehicle")
            templates = {
                tuple(vehicle.find("route").get("edges", "").split()) for vehicle in vehicles
            }
            for route in templates:
                edges = [self.net.getEdge(edge_id) for edge_id in route]
                self.assertTrue(all(edge.allows("passenger") for edge in edges), route)
                for current, following in zip(edges, edges[1:]):
                    self.assertTrue(
                        any(
                            connection.getFromLane().allows("passenger")
                            and connection.getToLane().allows("passenger")
                            for connection in current.getConnections(following)
                        ),
                        f"{profile}: disconnected {current.getID()} -> {following.getID()}",
                    )

    def test_j5_18_template_has_no_repeated_tls_or_uturn(self) -> None:
        for profile in EXPECTED_COUNTS:
            vehicles = ET.parse(ROOT / "demand" / f"{profile}.rou.xml").getroot().findall("vehicle")
            selected = [vehicle for vehicle in vehicles if f"{profile}.J5.18." in vehicle.get("id", "")]
            templates = {
                tuple(vehicle.find("route").get("edges", "").split()) for vehicle in selected
            }
            self.assertEqual(len(templates), 1, profile)
            route = next(iter(templates))
            self.assertIn(J5_18_EDGE, route)
            self.assertEqual(len(route), len(set(route)), profile)
            traffic_lights = []
            for current_id, following_id in zip(route, route[1:]):
                current = self.net.getEdge(current_id)
                following = self.net.getEdge(following_id)
                connections = current.getConnections(following)
                self.assertFalse(any(connection.getDirection().upper() == "T" for connection in connections))
                traffic_lights.extend(sorted({
                    connection.getTLSID() for connection in connections if connection.getTLSID()
                }))
            self.assertEqual(len(traffic_lights), len(set(traffic_lights)), profile)
            self.assertEqual(traffic_lights.count(J5_18_TLS), 1, profile)

    def test_generated_routes_do_not_use_uturn_connections(self) -> None:
        network = ET.parse(ROOT / "london.net.xml").getroot()
        uturns = {
            (connection.get("from"), connection.get("to"))
            for connection in network.findall("connection")
            if connection.get("dir") == "T"
        }
        for profile in EXPECTED_COUNTS:
            vehicles = ET.parse(ROOT / "demand" / f"{profile}.rou.xml").getroot().findall("vehicle")
            for vehicle in vehicles:
                edges = vehicle.find("route").get("edges", "").split()
                self.assertFalse(
                    any(pair in uturns for pair in zip(edges, edges[1:])),
                    f"{vehicle.get('id')} uses a generated U-turn",
                )

    def test_configs_preserve_network_and_enable_collision_checks(self) -> None:
        for profile in EXPECTED_COUNTS:
            config = ET.parse(ROOT / "configs" / f"{profile}.sumocfg").getroot()
            self.assertEqual(config.find("./input/net-file").get("value"), "../london.net.xml")
            self.assertEqual(
                config.find("./processing/collision.check-junctions").get("value"), "true"
            )


if __name__ == "__main__":
    unittest.main()
