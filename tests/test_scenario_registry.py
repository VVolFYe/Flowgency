"""Scenario registry and London static geometry tests."""

from __future__ import annotations

import unittest

from backend.simulation.geometry import _load_cached, get_scenario_geometry
from backend.simulation.scenarios import (
    DEFAULT_SCENARIO_ID,
    ScenarioNotFound,
    get_scenario,
    list_scenarios,
)


class ScenarioRegistryTests(unittest.TestCase):
    def test_registry_has_stable_ids_and_real_files(self) -> None:
        ids = [item["scenario_id"] for item in list_scenarios()]
        self.assertEqual(
            ids,
            [
                "single_intersection",
                "london_normal",
                "london_rush_hour",
                "london_unbalanced",
            ],
        )
        self.assertEqual(DEFAULT_SCENARIO_ID, "single_intersection")
        for scenario_id in ids:
            scenario = get_scenario(scenario_id)
            self.assertTrue(scenario.config_path.is_file())
            self.assertTrue(scenario.network_path.is_file())

    def test_london_metadata_preserves_mapping_ambiguity(self) -> None:
        london = next(item for item in list_scenarios() if item["scenario_id"] == "london_normal")
        targets = {item["intersection_id"]: item for item in london["target_mappings"]}
        self.assertEqual(len(targets), 5)
        self.assertIn("ambiguous", targets["J2"]["mapping_status"])
        self.assertEqual(len(targets["J5"]["candidates"]), 2)

    def test_invalid_scenario(self) -> None:
        with self.assertRaises(ScenarioNotFound):
            get_scenario("unknown")


class LondonGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.geometry = get_scenario_geometry("london_normal")

    def test_london_geometry_and_projection(self) -> None:
        geometry = self.geometry
        self.assertEqual(geometry["scenario_selection_id"], "london_normal")
        self.assertEqual(geometry["scenario_id"], "london-oval-kennington-v1")
        self.assertEqual(len(geometry["traffic_lights"]), 23)
        self.assertIn("+proj=utm", geometry["projection"]["proj_parameter"])
        self.assertTrue(geometry["rendering"]["invert_y_axis_for_screen"])
        self.assertGreater(len(geometry["edges"]), 1000)
        self.assertTrue(geometry["controlled_links"])

    def test_geometry_coordinates_share_bounds_and_cache_is_defensive(self) -> None:
        bounds = self.geometry["bounds"]
        for traffic_light in self.geometry["traffic_lights"]:
            for junction in traffic_light["junctions"]:
                self.assertGreaterEqual(junction["x_m"], bounds["min_x_m"])
                self.assertLessEqual(junction["x_m"], bounds["max_x_m"])
                self.assertGreaterEqual(junction["y_m"], bounds["min_y_m"])
                self.assertLessEqual(junction["y_m"], bounds["max_y_m"])

        before = _load_cached.cache_info().hits
        first = get_scenario_geometry("london_normal")
        first["edges"].clear()
        second = get_scenario_geometry("london_normal")
        self.assertGreater(_load_cached.cache_info().hits, before)
        self.assertGreater(len(second["edges"]), 1000)


if __name__ == "__main__":
    unittest.main()
