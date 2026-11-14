"""Focused accounting/configuration tests for the isolated AI fixed run."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from backend.simulation.ai_fixed_run import (
    read_event_totals,
    read_fixed_program,
    read_planned_demand,
    read_tripinfo,
    write_runtime_config,
)


ROOT = Path(__file__).resolve().parents[1]
NETWORK = ROOT / "scenarios" / "single_intersection" / "demo.net.xml"


class AiFixedRunTests(unittest.TestCase):
    def test_runtime_config_is_isolated_and_uses_existing_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            route = directory / "ai.rou.xml"
            route.write_text("<routes/>", encoding="utf-8")
            config = directory / "runtime.sumocfg"
            write_runtime_config(
                config,
                network_path=NETWORK,
                route_path=route,
                tripinfo_path=directory / "tripinfo.xml",
                summary_path=directory / "summary.xml",
                collision_path=directory / "collisions.xml",
                max_simulation_time_s=1800,
            )
            root = ET.parse(config).getroot()
        self.assertEqual(root.find("./input/net-file").get("value"), str(NETWORK.resolve()))
        self.assertEqual(root.find("./time/step-length").get("value"), "1")
        self.assertEqual(root.find("./time/end").get("value"), "1800")
        self.assertEqual(root.find("./processing/time-to-teleport").get("value"), "300")
        self.assertFalse(root.findall("tlLogic"))

    def test_fixed_program_is_unchanged(self) -> None:
        program = read_fixed_program(NETWORK)
        self.assertEqual(program["program_id"], "fixed")
        self.assertEqual(
            [phase["duration_s"] for phase in program["phases"]],
            [30.0, 3.0, 2.0, 30.0, 3.0, 2.0],
        )
        self.assertEqual(
            [phase["state"] for phase in program["phases"]],
            ["GrGr", "yryr", "rrrr", "rGrG", "ryry", "rrrr"],
        )

    def test_planned_and_actual_insertion_accounting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            route = directory / "demand.rou.xml"
            route.write_text(
                '<routes><vehicle id="ai_north_1" depart="0.542"/>'
                '<vehicle id="ai_east_2" depart="0.542"/></routes>',
                encoding="utf-8",
            )
            tripinfo = directory / "tripinfo.xml"
            tripinfo.write_text(
                '<tripinfos>'
                '<tripinfo id="ai_north_1" depart="1" departDelay="0.458" arrival="31" '
                'waitingTime="5" timeLoss="8" duration="30"/>'
                '<tripinfo id="ai_east_2" depart="3" departDelay="2.458" arrival="35" '
                'waitingTime="6" timeLoss="10" duration="32"/>'
                '</tripinfos>',
                encoding="utf-8",
            )
            planned = read_planned_demand(route)
            records, errors = read_tripinfo(tripinfo, planned)
        self.assertFalse(errors)
        self.assertEqual(planned, {"ai_north_1": 0.542, "ai_east_2": 0.542})
        self.assertEqual([item["insertion_delay_s"] for item in records], [0.458, 2.458])
        self.assertTrue(all(item["arrived"] for item in records))

    def test_summary_event_counts_are_accumulated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary = Path(temporary) / "summary.xml"
            summary.write_text(
                '<summary><step time="0" collisions="0" teleports="0"/>'
                '<step time="1" collisions="2" teleports="1"/>'
                '<step time="2" collisions="0" teleports="0"/></summary>',
                encoding="utf-8",
            )
            self.assertEqual(read_event_totals(summary), (2, 1, 2.0))


if __name__ == "__main__":
    unittest.main()
