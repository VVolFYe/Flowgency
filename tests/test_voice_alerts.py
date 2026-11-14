"""Voice events are driven by confirmed traffic changes, never UI actions."""

from __future__ import annotations

import unittest

from backend.voice.alerts import VoiceAlertPolicy


def snapshot(time_s: float, *, run_id: str = "run-1", vehicle: str | None = None,
             approach: str | None = None, phase: str = "north_south_green",
             state: str = "GrGr", plan: dict[str, float] | None = None,
             queue: int = 0) -> dict:
    result = {
        "run_id": run_id,
        "simulation_time_s": time_s,
        "current_phase_id": phase,
        "traffic_light_state": state,
        "network_queue": {"vehicles": queue, "measurement": "sumo_halting_number_unique_controlled_lanes"},
    }
    if vehicle is not None or approach is not None:
        result["emergency_priority"] = {"active_vehicle_id": vehicle, "active_approach": approach}
    if plan is not None:
        result["adaptive_control"] = {"last_cycle_decision": {"green_durations_s": plan}}
    return result


class VoiceAlertTests(unittest.TestCase):
    def test_conflicting_emergency_waits_for_confirmed_green(self) -> None:
        policy = VoiceAlertPolicy()
        first = snapshot(5, vehicle="ambulance-1", approach="eastbound_in")
        self.assertEqual([a["message_id"] for a in policy.observe(first)], ["emergency.requested"])
        self.assertEqual(policy.observe(snapshot(6, vehicle="ambulance-1", approach="eastbound_in")), [])
        self.assertEqual(policy.observe(snapshot(7, vehicle="ambulance-1", approach="eastbound_in", phase="north_south_yellow", state="yryr")), [])
        green = policy.observe(snapshot(10, vehicle="ambulance-1", approach="eastbound_in", phase="east_west_green", state="rGrG"))
        self.assertEqual([a["message_id"] for a in green], ["emergency.green_confirmed"])
        self.assertEqual(policy.observe(snapshot(11)), [])
        self.assertEqual(policy.observe(snapshot(12)), [])

    def test_compatible_emergency_uses_one_combined_message(self) -> None:
        policy = VoiceAlertPolicy(language="ro")
        alerts = policy.observe(snapshot(2, vehicle="fire-1", approach="northbound_in"))
        self.assertEqual([a["message_id"] for a in alerts], ["emergency.already_green"])
        self.assertEqual(alerts[0]["language"], "ro")
        self.assertEqual(policy.observe(snapshot(3, vehicle="fire-1", approach="northbound_in")), [])
        self.assertEqual(policy.get(alerts[0]["event_id"]), alerts[0])

    def test_cycle_plan_changes_do_not_trigger_voice(self) -> None:
        policy = VoiceAlertPolicy()
        plan = {"brixton": 42, "vassall_caldwell": 42}
        self.assertEqual(policy.observe(snapshot(0, plan=plan)), [])
        self.assertEqual(policy.observe(snapshot(90, plan=plan)), [])
        self.assertEqual(policy.observe(snapshot(180, plan={"brixton": 54, "vassall_caldwell": 30})), [])
        self.assertEqual(policy.observe(snapshot(181, plan={"brixton": 54, "vassall_caldwell": 30})), [])

    def test_congestion_disabled_by_default_and_sustained_when_configured(self) -> None:
        self.assertEqual(VoiceAlertPolicy().observe(snapshot(12, queue=10)), [])
        policy = VoiceAlertPolicy(congestion_threshold_vehicles=5)
        self.assertEqual(policy.observe(snapshot(0, queue=5)), [])
        self.assertEqual(policy.observe(snapshot(9, queue=6)), [])
        self.assertEqual([a["message_id"] for a in policy.observe(snapshot(10, queue=6))], ["traffic.congestion_sustained"])
        self.assertEqual(policy.observe(snapshot(11, queue=6)), [])
        policy.observe(snapshot(20, queue=2))
        self.assertEqual(policy.observe(snapshot(30, queue=6)), [])
        self.assertEqual(policy.observe(snapshot(40, queue=6)), [])  # 60-s cooldown
        self.assertEqual([a["message_id"] for a in policy.observe(snapshot(70, queue=6))], ["traffic.congestion_sustained"])

    def test_new_run_resets_history(self) -> None:
        policy = VoiceAlertPolicy()
        first = policy.observe(snapshot(1, vehicle="police-1", approach="northbound_in"))
        second = policy.observe(snapshot(1, run_id="run-2", vehicle="police-1", approach="northbound_in"))
        self.assertNotEqual(first[0]["event_id"], second[0]["event_id"])
        self.assertIsNone(policy.get(first[0]["event_id"]))

    def test_same_vehicle_is_not_announced_twice_in_one_run(self) -> None:
        policy = VoiceAlertPolicy()
        policy.observe(snapshot(1, vehicle="ambulance-1", approach="northbound_in"))
        policy.observe(snapshot(2))
        self.assertEqual(policy.observe(snapshot(3, vehicle="ambulance-1", approach="northbound_in")), [])
        self.assertEqual(policy.observe(snapshot(4)), [])


if __name__ == "__main__":
    unittest.main()
