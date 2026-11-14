"""Validate that the comparison rejects unsafe phase traces."""

from __future__ import annotations

import unittest

from backend.simulation.compare import validate_phases


class PhaseValidationTests(unittest.TestCase):
    def test_complete_safe_fixed_cycle(self) -> None:
        changes = [
            (0, "north_south_green"), (30, "north_south_yellow"),
            (33, "all_red_after_north_south"), (35, "east_west_green"),
            (65, "east_west_yellow"), (68, "all_red_after_east_west"),
            (70, "north_south_green"),
        ]
        self.assertEqual(validate_phases(changes, "fixed"), [])

    def test_skipped_clearance_and_short_green_fail(self) -> None:
        self.assertTrue(validate_phases([(0, "north_south_green"), (8, "east_west_green")], "adaptive"))
        self.assertTrue(validate_phases([(0, "north_south_green"), (8, "north_south_yellow")], "adaptive"))

    def test_only_initial_fixed_green_allows_sumo_step_offset(self) -> None:
        self.assertEqual(validate_phases([(0, "north_south_green"), (31, "north_south_yellow")], "fixed"), [])
        changes = [
            (0, "north_south_green"), (31, "north_south_yellow"),
            (34, "all_red_after_north_south"), (36, "east_west_green"),
            (67, "east_west_yellow"),
        ]
        self.assertTrue(validate_phases(changes, "fixed"))


if __name__ == "__main__":
    unittest.main()
