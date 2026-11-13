"""Narrow SUMO audit of the emergency demo's actual phase sequence."""

from __future__ import annotations

import shutil
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from backend.simulation.runner import SumoRunner


ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "scenarios" / "single_intersection"
PHASES = (
    "north_south_green",
    "north_south_yellow",
    "all_red_after_north_south",
    "east_west_green",
    "east_west_yellow",
    "all_red_after_east_west",
)


@unittest.skipUnless(shutil.which("sumo"), "SUMO is not installed")
class EmergencySumoTests(unittest.TestCase):
    def test_emergency_demo_preserves_clearance_and_completes(self) -> None:
        runner = SumoRunner(
            SCENARIO / "emergency.sumocfg",
            SCENARIO / "mappings.json",
            control_mode="adaptive_with_emergency_priority",
        )
        phase_changes: list[tuple[float, str]] = []
        priority_reasons: set[str] = set()
        arrived = collisions = teleports = steps = 0
        with runner:
            initial = runner.extract_snapshot()
            phase_changes.append((initial["simulation_time_s"], initial["current_phase_id"]))
            while runner.has_pending_vehicles() and steps < 500:
                runner.advance()
                steps += 1
                snapshot = runner.extract_snapshot()
                phase = snapshot["current_phase_id"]
                if phase != phase_changes[-1][1]:
                    phase_changes.append((snapshot["simulation_time_s"], phase))
                priority_reasons.add(snapshot["control_reason"])
                arrived += runner.connection.simulation.getArrivedNumber()
                collisions += runner.connection.simulation.getCollidingVehiclesNumber()
                teleports += runner.connection.simulation.getStartingTeleportNumber()
            self.assertFalse(runner.has_pending_vehicles(), "emergency run did not finish")

        self.assertEqual((arrived, collisions, teleports), (123, 0, 0))
        self.assertIn("request_normal_clearance_for_emergency", priority_reasons)
        self.assertIn("hold_compatible_green_for_emergency", priority_reasons)
        for (began, phase), (ended, following) in zip(phase_changes, phase_changes[1:]):
            self.assertEqual(following, PHASES[(PHASES.index(phase) + 1) % len(PHASES)])
            duration = ended - began
            if phase.endswith("_green"):
                self.assertGreaterEqual(duration, 10)
            elif phase.endswith("_yellow"):
                self.assertEqual(duration, 3)
            else:
                self.assertEqual(duration, 2)

        trips = ET.parse(SCENARIO / "output" / "emergency" / "tripinfo.xml").getroot()
        emergency = {
            trip.attrib["id"]: trip.attrib
            for trip in trips.findall("tripinfo")
            if trip.attrib["id"].startswith("emergency_")
        }
        self.assertEqual(set(emergency), {"emergency_ambulance_1", "emergency_fire_1", "emergency_police_1"})
        self.assertTrue(all(float(trip["arrival"]) > 0 for trip in emergency.values()))


if __name__ == "__main__":
    unittest.main()
