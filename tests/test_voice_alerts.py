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


def event_snapshot(time_s: float, events: list[dict], *, run_id: str = "run-1") -> dict:
    return {
        "run_id": run_id,
        "simulation_time_s": time_s,
        "emergency_events": events,
        "network_queue": {"vehicles": 0, "measurement": "sumo_halting_number_unique_controlled_lanes"},
    }


def emergency_event(event_id: str, vehicle_id: str, intersection_id: str, state: str = "detected") -> dict:
    return {
        "event_id": event_id,
        "emergency_vehicle_id": vehicle_id,
        "intersection_id": intersection_id,
        "state": state,
    }


class VoiceAlertTests(unittest.TestCase):
    def london_snapshot(self, time_s: float, events: list[dict], *, mode: str = "adaptive_network", run_id: str = "run-1", reverse: bool = False) -> dict:
        result = event_snapshot(time_s, events, run_id=run_id)
        result["active_configuration"] = {"network": "london", "controller_mode": mode}
        ids = ["GS_26546583", "GS_cluster_10218369045_4202836241_63951016"]
        result["traffic_light_controllers"] = dict.fromkeys(reversed(ids) if reverse else ids, {})
        return result

    def test_london_names_use_full_inventory_before_emergency_arrival(self) -> None:
        policy = VoiceAlertPolicy()
        self.assertEqual(policy.observe(self.london_snapshot(0, [], reverse=True)), [])
        raw_id = "GS_cluster_10218369045_4202836241_63951016"
        alerts = policy.observe(self.london_snapshot(1, [emergency_event("e2", "a2", raw_id)]))
        self.assertEqual(alerts[0]["text"], "Emergency vehicle detected at intersection 2.")
        self.assertEqual(alerts[0]["intersection_id"], raw_id)

    def test_london_names_are_equal_across_modes_and_reset(self) -> None:
        for mode in ("fixed_timing", "adaptive_network", "adaptive_emergency_priority"):
            with self.subTest(mode=mode):
                policy = VoiceAlertPolicy()
                for run_id in ("run-1", "run-2"):
                    events = [emergency_event("e1", "a1", "GS_26546583")]
                    alerts = policy.observe(self.london_snapshot(1, events, mode=mode, run_id=run_id, reverse=True))
                    self.assertEqual(alerts[0]["text"], "Emergency vehicle detected at intersection 1.")

    def test_london_aggregates_speak_numbers_without_raw_ids(self) -> None:
        policy = VoiceAlertPolicy()
        events = [
            emergency_event("e2", "a2", "GS_cluster_10218369045_4202836241_63951016"),
            emergency_event("e1", "a1", "GS_26546583"),
        ]
        detected = policy.observe(self.london_snapshot(1, events))
        self.assertEqual(policy.aggregate([a["event_id"] for a in detected])["text"], "Emergency vehicles detected at intersections 1 and 2.")
        active_events = [{**event, "state": "priority_active"} for event in events]
        active = policy.observe(self.london_snapshot(2, active_events, mode="adaptive_emergency_priority"))
        self.assertEqual(policy.aggregate([a["event_id"] for a in active])["text"], "Emergency priority activated at intersections 1 and 2.")
        completed = policy.observe(self.london_snapshot(3, [{**event, "state": "completed"} for event in events]))
        self.assertTrue(all("GS_" not in alert["text"] for alert in completed))
        self.assertEqual(len(completed), 2)

    def test_london_romanian_aggregation_is_localized(self) -> None:
        policy = VoiceAlertPolicy(language="ro")
        events = [emergency_event("e1", "a1", "GS_26546583"), emergency_event("e2", "a2", "GS_26546583")]
        alerts = policy.observe(self.london_snapshot(1, events))
        self.assertEqual(policy.aggregate([a["event_id"] for a in alerts])["text"], "2 vehicule de intervenție detectate la intersecția 1.")

    def test_later_unknown_controller_does_not_rename_existing_intersections(self) -> None:
        policy = VoiceAlertPolicy()
        policy.observe(self.london_snapshot(0, []))
        event = emergency_event("new", "a3", "GS_000new")
        new = policy.observe(self.london_snapshot(1, [event]))
        self.assertIn("intersection 3", new[0]["text"])
        original = emergency_event("old", "a1", "GS_26546583")
        alerts = policy.observe(self.london_snapshot(2, [event, original]))
        self.assertIn("intersection 1", alerts[0]["text"])

    def test_simultaneous_events_aggregate_same_and_different_intersections(self) -> None:
        policy = VoiceAlertPolicy()
        emitted = policy.observe(event_snapshot(5, [
            emergency_event("e1", "ambulance-1", "J1"),
            emergency_event("e2", "ambulance-2", "J1"),
        ]))
        grouped = policy.aggregate([item["event_id"] for item in emitted])
        self.assertEqual(grouped["text"], "2 emergency vehicles detected at intersection J1.")

        policy = VoiceAlertPolicy()
        emitted = policy.observe(event_snapshot(5, [
            emergency_event("e1", "ambulance-1", "J1"),
            emergency_event("e2", "ambulance-2", "J3"),
        ]))
        grouped = policy.aggregate([item["event_id"] for item in emitted])
        self.assertEqual(grouped["text"], "Emergency vehicles detected at intersections J1 and J3.")

    def test_priority_is_announced_only_for_real_priority_state(self) -> None:
        policy = VoiceAlertPolicy()
        first = policy.observe(event_snapshot(1, [emergency_event("e1", "ambulance-1", "J1")]))
        self.assertEqual([item["message_id"] for item in first], ["emergency.detected"])
        active = policy.observe(event_snapshot(2, [emergency_event("e1", "ambulance-1", "J1", "priority_active")]))
        self.assertEqual([item["message_id"] for item in active], ["emergency.priority_activated"])
        completed = policy.observe(event_snapshot(3, []))
        self.assertEqual([item["message_id"] for item in completed], ["emergency.priority_completed"])

    def test_aggregate_rejects_unknown_or_cross_run_ids(self) -> None:
        policy = VoiceAlertPolicy()
        emitted = policy.observe(event_snapshot(1, [emergency_event("e1", "a1", "J1")]))
        self.assertIsNone(policy.aggregate(["unknown"]))
        self.assertEqual(policy.aggregate([emitted[0]["event_id"]])["text"], emitted[0]["text"])
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
