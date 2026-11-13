"""Adapter checks use a deterministic TraCI double, without SUMO installed."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.simulation.cycle_adapter import AdaptiveSignal

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scenarios" / "single_intersection" / "adaptive.json"


class Light:
    def __init__(self, spec: dict) -> None:
        self.spec = spec
        self.phase = 0
        self.requests: list[tuple[int, float]] = []

    def getIDList(self) -> tuple[str, ...]:
        return ("demo_01",)

    def getProgram(self, _: str) -> str:
        return "fixed"

    def getAllProgramLogics(self, _: str) -> list:
        phases = [SimpleNamespace(state=p["state"], duration=p["duration_s"]) for p in self.spec["phases"]]
        return [SimpleNamespace(programID="fixed", phases=phases)]

    def getControlledLinks(self, _: str) -> list:
        return [[(lane, "out", "via")] for lane in ("south_in_0", "east_in_0", "north_in_0", "west_in_0")]

    def getPhase(self, _: str) -> int:
        return self.phase

    def getRedYellowGreenState(self, _: str) -> str:
        return self.spec["phases"][self.phase]["state"]

    def getSpentDuration(self, _: str) -> float:
        return 0.0 if self.phase == 0 else 1.0

    def setPhaseDuration(self, _: str, duration: float) -> None:
        self.requests.append((self.phase, duration))


class Lanes:
    def getLastStepHaltingNumber(self, lane: str) -> int:
        return 10 if lane in {"south_in_0", "north_in_0"} else 0


class CycleAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = json.loads(MANIFEST.read_text(encoding="utf-8"))["controllers"][0]
        self.light = Light(self.spec)
        self.connection = SimpleNamespace(trafficlight=self.light, lane=Lanes())

    def test_green_only_and_fixed_transition_order(self) -> None:
        signal = AdaptiveSignal(self.spec, self.connection)
        event = signal.tick()
        self.assertEqual(event["green_durations_s"], {"north_south": 40, "east_west": 20})
        for phase in range(1, 6):
            self.light.phase = phase
            signal.tick()
        self.assertEqual(self.light.requests, [(0, 40), (3, 19)])

    def test_mismatched_program_fails_before_control(self) -> None:
        self.spec["phases"][1]["state"] = "rrrr"
        self.light = Light(json.loads(MANIFEST.read_text(encoding="utf-8"))["controllers"][0])
        with self.assertRaises(ValueError):
            AdaptiveSignal(self.spec, SimpleNamespace(trafficlight=self.light, lane=Lanes()))

    def test_skipped_phase_stops_control(self) -> None:
        signal = AdaptiveSignal(self.spec, self.connection)
        signal.tick()
        self.light.phase = 2
        with self.assertRaises(RuntimeError):
            signal.tick()


if __name__ == "__main__":
    unittest.main()
