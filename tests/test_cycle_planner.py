"""Contract tests for the SUMO-independent cycle planner."""

from __future__ import annotations

import unittest

from backend.controller.cycle_planner import CycleConfig, FixedPhase, GreenGroup, plan_cycle


def j3_config() -> CycleConfig:
    return CycleConfig(
        intersection_id="J3",
        groups=(
            GreenGroup("brixton", "j3_phase_0", 20, 64),
            GreenGroup("vassall_caldwell", "j3_phase_2", 20, 64),
        ),
        fixed_phases=(FixedPhase("j3_phase_1_yellow", 3), FixedPhase("j3_phase_3_yellow", 3)),
        green_budget_s=84,
        phase_order=("j3_phase_0", "j3_phase_1_yellow", "j3_phase_2", "j3_phase_3_yellow"),
    )


class CyclePlannerTests(unittest.TestCase):
    def test_equal_and_zero_queues_are_equal(self) -> None:
        for queues in ({"brixton": 5, "vassall_caldwell": 5}, {"brixton": 0, "vassall_caldwell": 0}):
            plan = plan_cycle(j3_config(), queues)
            self.assertEqual(plan.green_durations_s, {"brixton": 42, "vassall_caldwell": 42})
            self.assertEqual(plan.phase_durations_s["j3_phase_1_yellow"], 3)

    def test_skew_clamps_both_groups_and_preserves_budget(self) -> None:
        plan = plan_cycle(j3_config(), {"brixton": 100, "vassall_caldwell": 0})
        self.assertEqual(plan.green_durations_s, {"brixton": 64, "vassall_caldwell": 20})
        self.assertEqual(sum(plan.green_durations_s.values()), 84)

    def test_previous_plan_limits_cycle_change(self) -> None:
        plan = plan_cycle(
            j3_config(), {"brixton": 100, "vassall_caldwell": 0},
            {"brixton": 42, "vassall_caldwell": 42},
        )
        self.assertEqual(plan.green_durations_s, {"brixton": 54, "vassall_caldwell": 30})

    def test_three_groups_preserve_bounds_and_budget(self) -> None:
        config = CycleConfig(
            "demo_03",
            tuple(GreenGroup(f"g{i}", f"p{i}", 10, 50) for i in range(3)),
            (FixedPhase("transition", 4),),
            90,
            ("p0", "transition", "p1", "p2"),
        )
        plan = plan_cycle(config, {"g0": 0, "g1": 1, "g2": 30})
        self.assertAlmostEqual(sum(plan.green_durations_s.values()), 90)
        self.assertTrue(all(10 <= value <= 50 for value in plan.green_durations_s.values()))

    def test_missing_negative_and_infeasible_inputs_fail(self) -> None:
        for queues in ({"brixton": 1}, {"brixton": -1, "vassall_caldwell": 0}):
            with self.assertRaises(ValueError):
                plan_cycle(j3_config(), queues)
        with self.assertRaises(ValueError):
            plan_cycle(CycleConfig("J3", j3_config().groups, (), 10, ("j3_phase_0", "j3_phase_2")), {"brixton": 1, "vassall_caldwell": 1})


if __name__ == "__main__":
    unittest.main()
