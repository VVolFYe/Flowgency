"""Real-SUMO regression for synthetic adaptive phase transitions."""

from __future__ import annotations

import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from backend.simulation.runner import SumoRunner


ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "scenarios" / "single_intersection"
EXPECTED_PHASES = (
    "north_south_green",
    "north_south_yellow",
    "all_red_after_north_south",
    "east_west_green",
    "east_west_yellow",
    "all_red_after_east_west",
)


@unittest.skipUnless(shutil.which("sumo"), "SUMO binary is required")
class SyntheticAdaptiveSumoTests(unittest.TestCase):
    def run_scenario(self, mode: str) -> dict:
        with tempfile.TemporaryDirectory(prefix=f"flowgency-{mode}-") as temporary:
            directory = Path(temporary)
            config = directory / "scenario.sumocfg"
            tripinfo = directory / "tripinfo.xml"
            summary = directory / "summary.xml"
            config.write_text(
                f"""<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <input>
    <net-file value="{SCENARIO / 'demo.net.xml'}"/>
    <route-files value="{SCENARIO / 'demo.rou.xml'}"/>
  </input>
  <time><begin value="0"/><end value="650"/><step-length value="1"/></time>
  <random_number><seed value="42"/></random_number>
  <output>
    <tripinfo-output value="{tripinfo}"/>
    <tripinfo-output.write-unfinished value="true"/>
    <summary-output value="{summary}"/>
  </output>
  <processing><collision.action value="warn"/><time-to-teleport value="-1"/></processing>
  <report><verbose value="false"/><no-step-log value="true"/></report>
</configuration>
""",
                encoding="utf-8",
            )
            runner = SumoRunner(
                config_path=config,
                mapping_path=SCENARIO / "mappings.json",
                output_directory=directory,
                control_mode=mode,
            )
            transitions: list[tuple[float, int, str]] = []
            departed = arrived = collisions = teleports = 0
            try:
                runner.start()
                snapshot = runner.extract_snapshot()
                last_phase = int(snapshot["current_phase_index"])
                transitions.append(
                    (float(snapshot["simulation_time_s"]), last_phase, str(snapshot["current_phase_id"]))
                )
                while runner.has_pending_vehicles() and runner.connection.simulation.getTime() < 650:
                    runner.advance()
                    departed += int(runner.connection.simulation.getDepartedNumber())
                    arrived += int(runner.connection.simulation.getArrivedNumber())
                    collisions += int(runner.connection.simulation.getCollidingVehiclesNumber())
                    teleports += int(runner.connection.simulation.getStartingTeleportNumber())
                    snapshot = runner.extract_snapshot()
                    phase = int(snapshot["current_phase_index"])
                    if phase != last_phase:
                        transitions.append(
                            (float(snapshot["simulation_time_s"]), phase, str(snapshot["current_phase_id"]))
                        )
                        last_phase = phase
                final_snapshot = runner.extract_snapshot()
                pending = runner.has_pending_vehicles()
            finally:
                runner.close()

            trips = list(ET.parse(tripinfo).getroot().iter("tripinfo"))
            return {
                "departed": departed,
                "arrived": arrived,
                "collisions": collisions,
                "teleports": teleports,
                "pending": pending,
                "metrics": final_snapshot["metrics"],
                "trip_waiting": sum(float(item.get("waitingTime", "0")) for item in trips),
                "trip_ids": {item.get("id", "") for item in trips},
                "transitions": transitions,
            }

    def test_fixed_and_adaptive_complete_with_safe_phase_order(self) -> None:
        fixed = self.run_scenario("fixed")
        adaptive = self.run_scenario("adaptive")

        for result in (fixed, adaptive):
            self.assertFalse(result["pending"])
            self.assertEqual(result["departed"], 120)
            self.assertEqual(result["arrived"], 120)
            self.assertEqual(result["collisions"], 0)
            self.assertEqual(result["teleports"], 0)
            self.assertEqual(len(result["trip_ids"]), 120)
            self.assertEqual(result["metrics"]["total_waiting_time_s"], result["trip_waiting"])

            transitions = result["transitions"]
            for previous, current in zip(transitions, transitions[1:]):
                self.assertEqual(current[1], (previous[1] + 1) % len(EXPECTED_PHASES))
                self.assertEqual(current[2], EXPECTED_PHASES[current[1]])
            for entry, following in zip(transitions, transitions[1:]):
                duration = following[0] - entry[0]
                if entry[1] in (1, 4):
                    self.assertEqual(duration, 3.0)
                elif entry[1] in (2, 5):
                    self.assertEqual(duration, 2.0)

        self.assertEqual(fixed["metrics"]["total_waiting_time_s"], 1318.0)
        self.assertEqual(
            sum(vehicle.startswith("east_flow") for vehicle in adaptive["trip_ids"]), 30
        )
        self.assertEqual(
            sum(vehicle.startswith("west_flow") for vehicle in adaptive["trip_ids"]), 30
        )
        for entry, following in zip(
            adaptive["transitions"], adaptive["transitions"][1:]
        ):
            if entry[1] in (0, 3):
                self.assertGreaterEqual(following[0] - entry[0], 10.0)
                self.assertLessEqual(following[0] - entry[0], 45.0)


if __name__ == "__main__":
    unittest.main()
