"""Lightweight consistency tests for generated London demand profiles."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parent
EXPECTED_COUNTS = {"normal": 460, "rush_hour": 690, "unbalanced": 528}


class TrafficScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        mappings = json.loads((ROOT / "mapping_candidates.json").read_text(encoding="utf-8"))
        cls.mapped_edges = {
            edge
            for target in mappings["targets"]
            for candidate in target["candidates"]
            for edge in candidate["incoming_edges"]
        }

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

    def test_departures_are_ordered_and_bounded(self) -> None:
        for profile in EXPECTED_COUNTS:
            vehicles = ET.parse(ROOT / "demand" / f"{profile}.rou.xml").getroot().findall("vehicle")
            departures = [float(vehicle.get("depart")) for vehicle in vehicles]
            self.assertEqual(departures, sorted(departures), profile)
            self.assertGreaterEqual(min(departures), 0)
            self.assertLess(max(departures), 900)

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
