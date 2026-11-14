"""Paired vehicle comparison semantics."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.simulation.compare_cycles import compare, read_expected_vehicle_ids, read_tripinfo, validate_run


class CompareCyclesTests(unittest.TestCase):
    def test_positive_saving_and_same_vehicle_set(self) -> None:
        fixed = {"a": {"waiting_s": 10, "time_loss_s": 12, "duration_s": 30}}
        adaptive = {"a": {"waiting_s": 6, "time_loss_s": 7, "duration_s": 25}}
        result = compare(fixed, adaptive)
        self.assertEqual(result["waiting_s"]["average_saved"], 4)
        with self.assertRaises(ValueError):
            compare(fixed, {})

    def test_validation_rejects_unfinished_or_mismatched_demand(self) -> None:
        run = {
            "exit_code": 0,
            "terminated_by_step_limit": False,
            "departed": 2,
            "arrived": 2,
            "departed_vehicle_ids": ["a", "b"],
            "arrived_vehicle_ids": ["a", "b"],
            "collisions": 0,
            "teleports": 0,
        }
        tripinfo = {
            "completed_ids": {"a", "b"},
            "unfinished_ids": [],
            "duplicate_ids": [],
        }
        self.assertTrue(validate_run(run, tripinfo, {"a", "b"})["passed"])
        tripinfo["unfinished_ids"] = ["b"]
        self.assertFalse(validate_run(run, tripinfo, {"a", "b"})["passed"])

    def test_route_and_tripinfo_parsing_is_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            routes = directory / "demand.rou.xml"
            routes.write_text("<routes><vehicle id=\"a\"/></routes>", encoding="utf-8")
            config = directory / "scenario.sumocfg"
            config.write_text(
                "<configuration><input><route-files value=\"demand.rou.xml\"/></input></configuration>",
                encoding="utf-8",
            )
            tripinfo = directory / "tripinfo.xml"
            tripinfo.write_text(
                "<tripinfos><tripinfo id=\"a\" arrival=\"4\" waitingTime=\"1\" timeLoss=\"2\" duration=\"4\"/></tripinfos>",
                encoding="utf-8",
            )
            self.assertEqual(read_expected_vehicle_ids(config), {"a"})
            parsed = read_tripinfo(tripinfo)
            self.assertEqual(parsed["completed_ids"], {"a"})
            self.assertEqual(parsed["unfinished_ids"], [])


if __name__ == "__main__":
    unittest.main()
