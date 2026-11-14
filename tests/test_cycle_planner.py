"""Contract tests for the SUMO-independent cycle planner."""

from __future__ import annotations

import unittest

from backend.controller.cycle_planner import (
    CycleConfig,
    DemandObservation,
    FixedPhase,
    GreenGroup,
    PressurePolicy,
    plan_cycle,
    plan_pressure_cycle,
    pressure_score,
)


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

    def test_pressure_near_equal_and_zero_demand_use_baseline(self) -> None:
        baseline = {"brixton": 42.0, "vassall_caldwell": 42.0}
        for observations in (
            {
                "brixton": DemandObservation(0, 0, 0, 0),
                "vassall_caldwell": DemandObservation(0, 0, 0, 0),
            },
            {
                "brixton": DemandObservation(1, 4, 8, 0.1),
                "vassall_caldwell": DemandObservation(1, 5, 9, 0.1),
            },
        ):
            plan = plan_pressure_cycle(j3_config(), observations, baseline, baseline)
            self.assertEqual(plan.green_durations_s, baseline)
            self.assertEqual(plan.reason, "baseline_green_distribution_near_equal_demand")

    def test_pressure_uneven_demand_is_bounded_and_preserves_budget(self) -> None:
        baseline = {"brixton": 42.0, "vassall_caldwell": 42.0}
        observations = {
            "brixton": DemandObservation(0, 1, 0, 0),
            "vassall_caldwell": DemandObservation(12, 20, 45, 0.05),
        }
        plan = plan_pressure_cycle(j3_config(), observations, baseline, baseline)
        self.assertLess(plan.green_durations_s["brixton"], 42)
        self.assertGreater(plan.green_durations_s["vassall_caldwell"], 42)
        self.assertEqual(sum(plan.green_durations_s.values()), 84)
        self.assertTrue(all(30 <= value <= 54 for value in plan.green_durations_s.values()))

    def test_low_demand_confidence_stays_near_baseline(self) -> None:
        baseline = {"brixton": 42.0, "vassall_caldwell": 42.0}
        policy = PressurePolicy(low_demand_max_adjustment_s=0)
        for vehicles in range(4):
            plan = plan_pressure_cycle(
                j3_config(),
                {
                    "brixton": DemandObservation(0, 0, 0, 0),
                    "vassall_caldwell": DemandObservation(
                        vehicles, vehicles, 0, 0
                    ),
                },
                baseline,
                baseline,
                policy,
            )
            self.assertAlmostEqual(sum(plan.green_durations_s.values()), 84)
            self.assertEqual(plan.green_durations_s, baseline)

    def test_confidence_tiers_and_large_imbalance(self) -> None:
        baseline = {"brixton": 42.0, "vassall_caldwell": 42.0}
        policy = PressurePolicy(low_demand_max_adjustment_s=0)
        for vehicles, limit in ((4, 3), (10, 6), (20, 12)):
            plan = plan_pressure_cycle(
                j3_config(),
                {
                    "brixton": DemandObservation(0, 0, 0, 0),
                    "vassall_caldwell": DemandObservation(
                        vehicles, vehicles, 20, 0
                    ),
                },
                baseline,
                baseline,
                policy,
            )
            self.assertGreater(plan.green_durations_s["vassall_caldwell"], 42)
            self.assertLessEqual(
                plan.green_durations_s["vassall_caldwell"] - 42,
                limit + 1e-6,
            )
            self.assertAlmostEqual(sum(plan.green_durations_s.values()), 84)

    def test_sustained_waiting_overrides_low_demand_limit(self) -> None:
        baseline = {"brixton": 42.0, "vassall_caldwell": 42.0}
        plan = plan_pressure_cycle(
            j3_config(),
            {
                "brixton": DemandObservation(0, 0, 0, 0),
                "vassall_caldwell": DemandObservation(1, 1, 60, 0),
            },
            baseline,
            baseline,
            PressurePolicy(low_demand_max_adjustment_s=0),
        )
        self.assertGreater(plan.green_durations_s["vassall_caldwell"], 43)
        self.assertLessEqual(plan.green_durations_s["vassall_caldwell"], 54)
        self.assertAlmostEqual(sum(plan.green_durations_s.values()), 84)

    def test_multistage_confidence_preserves_budget_and_bounds(self) -> None:
        config = CycleConfig(
            "demo_03",
            tuple(GreenGroup(f"g{i}", f"p{i}", 18, 42) for i in range(3)),
            (FixedPhase("transition", 4),),
            90,
            ("p0", "transition", "p1", "p2"),
            max_change_s=6,
        )
        baseline = {"g0": 30.0, "g1": 30.0, "g2": 30.0}
        plan = plan_pressure_cycle(
            config,
            {
                "g0": DemandObservation(0, 0, 0, 0),
                "g1": DemandObservation(1, 2, 5, 0),
                "g2": DemandObservation(5, 10, 30, 0),
            },
            baseline,
            baseline,
            PressurePolicy(low_demand_max_adjustment_s=0),
        )
        self.assertAlmostEqual(sum(plan.green_durations_s.values()), 90)
        self.assertTrue(
            all(24 <= duration <= 36 for duration in plan.green_durations_s.values())
        )
        self.assertEqual(plan.phase_durations_s["transition"], 4)

    def test_downstream_blockage_reduces_stage_pressure(self) -> None:
        policy = PressurePolicy()
        open_score = pressure_score(DemandObservation(6, 12, 30, 0), policy)
        blocked_score = pressure_score(DemandObservation(6, 12, 30, 1), policy)
        self.assertLess(blocked_score, open_score)


if __name__ == "__main__":
    unittest.main()
