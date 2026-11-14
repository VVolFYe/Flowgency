from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.simulation.ai_adaptive_run import (
    compare_fixed_demand,
    validate_phase_transitions,
)


class AiAdaptiveRunTests(unittest.TestCase):
    def test_safe_phase_sequence_and_clearance_are_accepted(self) -> None:
        transitions = [
            {"simulation_time_s": 0, "phase_index": 0, "phase_id": "north_south_green"},
            {"simulation_time_s": 20, "phase_index": 1, "phase_id": "north_south_yellow"},
            {"simulation_time_s": 23, "phase_index": 2, "phase_id": "all_red_after_north_south"},
            {"simulation_time_s": 25, "phase_index": 3, "phase_id": "east_west_green"},
            {"simulation_time_s": 35, "phase_index": 4, "phase_id": "east_west_yellow"},
            {"simulation_time_s": 38, "phase_index": 5, "phase_id": "all_red_after_east_west"},
            {"simulation_time_s": 40, "phase_index": 0, "phase_id": "north_south_green"},
        ]
        self.assertEqual(validate_phase_transitions(transitions), [])

    def test_skipped_or_short_clearance_is_rejected(self) -> None:
        skipped = [
            {"simulation_time_s": 0, "phase_index": 0, "phase_id": "north_south_green"},
            {"simulation_time_s": 20, "phase_index": 2, "phase_id": "all_red_after_north_south"},
        ]
        short_yellow = [
            {"simulation_time_s": 0, "phase_index": 1, "phase_id": "north_south_yellow"},
            {"simulation_time_s": 2, "phase_index": 2, "phase_id": "all_red_after_north_south"},
        ]
        self.assertIn("unsafe phase order", validate_phase_transitions(skipped)[0])
        self.assertIn("yellow phase", validate_phase_transitions(short_yellow)[0])

    def test_fixed_demand_comparison_checks_ids_timestamps_and_bytes(self) -> None:
        content = """<?xml version='1.0'?><routes>
<vehicle id='ai_north_1' depart='1.5'/>
<vehicle id='ai_east_2' depart='2'/>
</routes>"""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            adaptive = directory / "adaptive.rou.xml"
            fixed = directory / "fixed.rou.xml"
            adaptive.write_text(content, encoding="utf-8")
            fixed.write_text(content, encoding="utf-8")
            comparison = compare_fixed_demand(adaptive, fixed)
        self.assertTrue(comparison["ids_match"])
        self.assertTrue(comparison["planned_departures_match"])
        self.assertTrue(comparison["route_file_sha256_match"])


if __name__ == "__main__":
    unittest.main()
