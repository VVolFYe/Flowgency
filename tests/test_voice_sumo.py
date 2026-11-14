"""End-to-end traffic alerts from the synthetic SUMO emergency scenario."""

from __future__ import annotations

import shutil
import time
import unittest

from backend.simulation.service import SimulationService


@unittest.skipUnless(shutil.which("sumo"), "SUMO is not installed")
class VoiceSumoTests(unittest.TestCase):
    def test_emergency_run_emits_confirmed_traffic_alerts(self) -> None:
        service = SimulationService()
        service.open()
        seen: dict[str, dict] = {}
        try:
            service.start(
                speed=100,
                network="single_intersection",
                traffic_profile="normal",
                controller_mode="adaptive_emergency_priority",
                emergency_vehicles_enabled=True,
            )
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                current = service.latest_snapshot()
                if current:
                    for alert in current.get("voice_alerts", []):
                        seen[alert["event_id"]] = alert
                state = service.status()["state"]
                if state == "finished":
                    break
                if state == "error":
                    self.fail(str(service.status()["error"]))
                time.sleep(0.02)
            else:
                self.fail("emergency simulation did not finish in time")
            message_ids = {alert["message_id"] for alert in seen.values()}
            self.assertIn("emergency.detected", message_ids)
            self.assertIn("emergency.priority_activated", message_ids)
            self.assertNotIn("emergency.request_ended", message_ids)
            self.assertTrue(all(alert["priority"] == "emergency" for alert in seen.values()))
            last = list(seen.values())[-1]
            self.assertEqual(service.voice_alert(last["event_id"]), last)
        finally:
            service.shutdown()


if __name__ == "__main__":
    unittest.main()
