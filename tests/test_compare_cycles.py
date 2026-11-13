"""Paired vehicle comparison semantics."""

from __future__ import annotations

import unittest

from backend.simulation.compare_cycles import compare


class CompareCyclesTests(unittest.TestCase):
    def test_positive_saving_and_same_vehicle_set(self) -> None:
        fixed = {"a": {"waiting_s": 10, "time_loss_s": 12, "duration_s": 30}}
        adaptive = {"a": {"waiting_s": 6, "time_loss_s": 7, "duration_s": 25}}
        result = compare(fixed, adaptive)
        self.assertEqual(result["waiting_s"]["average_saved"], 4)
        with self.assertRaises(ValueError):
            compare(fixed, {})


if __name__ == "__main__":
    unittest.main()
