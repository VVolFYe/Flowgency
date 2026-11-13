"""Safety and responsiveness checks for the synthetic junction policy."""

from __future__ import annotations

import unittest

from backend.controller.adaptive import AdaptiveConfig, AdaptiveState, decide


def snapshot(time_s: float, phase: str, ns: int, ew: int) -> dict:
    return {
        "simulation_time_s": time_s,
        "current_phase_id": phase,
        "traffic_light_state": "GrGr" if phase == "north_south_green" else "rGrG",
        "queue_lengths_by_approach": {
            "northbound_in": {"vehicles": ns, "measurement": "sumo_halting_number"},
            "southbound_in": {"vehicles": 0, "measurement": "sumo_halting_number"},
            "eastbound_in": {"vehicles": ew, "measurement": "sumo_halting_number"},
            "westbound_in": {"vehicles": 0, "measurement": "sumo_halting_number"},
        },
    }


class AdaptiveControllerTests(unittest.TestCase):
    def test_minimum_green_and_sustained_opposing_demand(self) -> None:
        config = AdaptiveConfig(smoothing=1)
        state = AdaptiveState()
        for second in range(13):
            decision, state = decide(snapshot(second, "north_south_green", 0, 8), state, config)
            if second < 10:
                self.assertEqual(decision.remaining_green_s, 2)
        self.assertEqual(decision.remaining_green_s, 1)
        self.assertEqual(decision.reason, "sustained_opposing_queue_advantage")

    def test_one_spike_does_not_switch(self) -> None:
        config = AdaptiveConfig(smoothing=1)
        state = AdaptiveState(phase_id="north_south_green", phase_started_s=0)
        for second, opposing in ((10, 8), (11, 0), (12, 0)):
            decision, state = decide(snapshot(second, "north_south_green", 0, opposing), state, config)
            self.assertEqual(decision.remaining_green_s, 2)

    def test_maximum_green_switches_even_without_opposing_queue(self) -> None:
        state = AdaptiveState(phase_id="north_south_green", phase_started_s=0)
        decision, _ = decide(snapshot(45, "north_south_green", 20, 0), state, AdaptiveConfig())
        self.assertEqual(decision.reason, "maximum_green_reached")
        self.assertEqual(decision.remaining_green_s, 1)

    def test_missing_measurement_and_clearance_never_issue_command(self) -> None:
        state = AdaptiveState()
        observed = snapshot(12, "north_south_green", 1, 3)
        del observed["queue_lengths_by_approach"]["eastbound_in"]
        decision, _ = decide(observed, state, AdaptiveConfig())
        self.assertIsNone(decision.remaining_green_s)
        observed["current_phase_id"] = "north_south_yellow"
        observed["traffic_light_state"] = "yryr"
        decision, _ = decide(observed, state, AdaptiveConfig())
        self.assertIsNone(decision.remaining_green_s)

    def test_anti_starvation_and_config_validation(self) -> None:
        config = AdaptiveConfig(max_red_s=20)
        state = AdaptiveState(phase_id="north_south_green", phase_started_s=0)
        decision, _ = decide(snapshot(20, "north_south_green", 20, 0), state, config)
        self.assertEqual(decision.reason, "opposing_approach_anti_starvation")
        with self.assertRaises(ValueError):
            AdaptiveConfig(min_green_s=45, max_green_s=45)


if __name__ == "__main__":
    unittest.main()
