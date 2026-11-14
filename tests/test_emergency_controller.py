"""Emergency preference keeps normal clearance and the global green minimum."""

import unittest

from backend.controller.emergency import EmergencyRequest, decide_emergency


AMBULANCE = EmergencyRequest("ambulance-1", "ambulance", "westbound_in", 4.0)


class EmergencyControllerTests(unittest.TestCase):
    def decide(self, elapsed: float, requests=(AMBULANCE,), active=None, phase="north_south_green", state="GrGr"):
        return decide_emergency(
            phase_id=phase,
            signal_state=state,
            phase_elapsed_s=elapsed,
            requests=tuple(requests),
            active_vehicle_id=active,
        )

    def test_conflicting_green_keeps_ten_second_minimum(self) -> None:
        before = self.decide(9.0)
        self.assertEqual(before.remaining_green_s, 2.0)
        self.assertEqual(before.reason, "minimum_green_protected_before_emergency")
        after = self.decide(10.0)
        self.assertEqual(after.remaining_green_s, 0.0)
        self.assertEqual(after.reason, "request_normal_clearance_for_emergency")

    def test_compatible_green_extends_beyond_normal_maximum(self) -> None:
        decision = self.decide(47.0, phase="east_west_green", state="rGrG")
        self.assertEqual(decision.remaining_green_s, 2.0)
        self.assertEqual(decision.reason, "hold_compatible_green_for_emergency")

    def test_clearance_and_unexpected_state_issue_no_command(self) -> None:
        self.assertIsNone(self.decide(2.0, phase="north_south_yellow", state="yryr").remaining_green_s)
        self.assertIsNone(self.decide(12.0, state="GGGG").remaining_green_s)

    def test_active_request_is_stable_then_earliest_wins(self) -> None:
        police = EmergencyRequest("police-1", "police", "northbound_in", 2.0)
        selected = self.decide(11.0, (AMBULANCE, police), active="ambulance-1")
        self.assertEqual(selected.active_vehicle_id, "ambulance-1")
        selected = self.decide(11.0, (AMBULANCE, police), active="departed")
        self.assertEqual(selected.active_vehicle_id, "police-1")
        self.assertIsNone(self.decide(11.0, ()).active_vehicle_id)

    def test_invalid_request_and_elapsed_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.decide(-1.0)
        with self.assertRaises(ValueError):
            self.decide(11.0, (EmergencyRequest("x", "bus", "westbound_in", 0.0),))


if __name__ == "__main__":
    unittest.main()
