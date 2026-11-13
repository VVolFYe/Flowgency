"""Validation for normalized geometry read from the real SUMO network."""

from __future__ import annotations

import unittest

from backend.simulation.geometry import get_network_geometry


class NetworkGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.geometry = get_network_geometry()

    def test_identity_coordinate_system_and_bounds(self) -> None:
        geometry = self.geometry
        self.assertEqual(geometry["scenario_id"], "single-intersection-v1")
        self.assertEqual(geometry["coordinate_system"], "synthetic_cartesian_metres")
        self.assertEqual(
            geometry["bounds"],
            {"min_x_m": 0.0, "min_y_m": -0.0, "max_x_m": 300.0, "max_y_m": 300.0},
        )
        self.assertTrue(all(isinstance(value, float) for value in geometry["bounds"].values()))

    def test_external_and_internal_lane_shapes(self) -> None:
        edges = {edge["edge_id"]: edge for edge in self.geometry["edges"]}
        self.assertEqual(len(edges), 12)
        self.assertEqual(sum(edge["is_internal"] for edge in edges.values()), 4)
        self.assertIn("east_in", edges)
        self.assertIn(":demo_01_0", edges)

        lane_ids = {
            lane["lane_id"]
            for edge in edges.values()
            for lane in edge["lanes"]
        }
        self.assertIn("east_in_0", lane_ids)
        self.assertIn(":demo_01_0_0", lane_ids)
        for edge in edges.values():
            for lane in edge["lanes"]:
                self.assertGreaterEqual(len(lane["shape"]), 2)
                for point in lane["shape"]:
                    self.assertIsInstance(point["x_m"], float)
                    self.assertIsInstance(point["y_m"], float)

    def test_junction_tls_and_controlled_link_mappings(self) -> None:
        junctions = {item["junction_id"]: item for item in self.geometry["junctions"]}
        self.assertEqual(len(junctions), 5)
        self.assertEqual(junctions["demo_01"]["type"], "traffic_light")
        self.assertEqual(junctions["demo_01"]["x_m"], 150.0)
        self.assertEqual(junctions["demo_01"]["y_m"], 150.0)
        self.assertGreater(len(junctions["demo_01"]["shape"]), 4)

        self.assertEqual(
            self.geometry["traffic_lights"],
            [
                {
                    "traffic_light_id": "demo_01",
                    "junctions": [
                        {"junction_id": "demo_01", "x_m": 150.0, "y_m": 150.0}
                    ],
                }
            ],
        )
        links = self.geometry["controlled_links"]
        self.assertEqual({link["link_index"] for link in links}, {0, 1, 2, 3})
        self.assertEqual(
            {link["from_lane"] for link in links},
            {"south_in_0", "east_in_0", "north_in_0", "west_in_0"},
        )

    def test_callers_receive_defensive_copies(self) -> None:
        first = get_network_geometry()
        first["edges"].clear()
        self.assertEqual(len(get_network_geometry()["edges"]), 12)


if __name__ == "__main__":
    unittest.main()
