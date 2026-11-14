"""Adapter checks use a deterministic TraCI double, without SUMO installed."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.controller.cycle_planner import CycleConfig, CyclePlan, FixedPhase, GreenGroup
from backend.simulation.cycle_adapter import (
    AdaptiveSignal,
    load_adaptive_signal_set,
    quantize_pressure_plan,
)

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


class DiscoveryLight:
    def __init__(self) -> None:
        self.programs = {
            "tls_a": [(30, "GGr"), (3, "yyr"), (30, "rrG"), (3, "rry")],
            "tls_b": [
                (27, "Grr"), (3, "yrr"), (27, "rGr"),
                (3, "ryr"), (27, "rrG"), (3, "rry"),
            ],
            "tls_bad": [(30, "G"), (3, "y"), (5, "r")],
            "tls_fixed": [(30, "G"), (3, "y"), (5, "r")],
        }
        self.phases = {traffic_light_id: 0 for traffic_light_id in self.programs}
        self.requests: list[tuple[str, int, float]] = []

    def getIDList(self) -> tuple[str, ...]:
        return tuple(self.programs)

    def getProgram(self, _: str) -> str:
        return "0"

    def getAllProgramLogics(self, traffic_light_id: str) -> list:
        phases = [
            SimpleNamespace(duration=duration, state=state)
            for duration, state in self.programs[traffic_light_id]
        ]
        return [SimpleNamespace(programID="0", phases=phases)]

    def getControlledLinks(self, traffic_light_id: str) -> list:
        state_length = len(self.programs[traffic_light_id][0][1])
        return [[(f"{traffic_light_id}_in_{index}", f"{traffic_light_id}_out_{index}", "via")]
                for index in range(state_length)]

    def getPhase(self, traffic_light_id: str) -> int:
        return self.phases[traffic_light_id]

    def getRedYellowGreenState(self, traffic_light_id: str) -> str:
        return self.programs[traffic_light_id][self.phases[traffic_light_id]][1]

    def getSpentDuration(self, _: str) -> float:
        return 0.0

    def setPhaseDuration(self, traffic_light_id: str, duration: float) -> None:
        self.requests.append((traffic_light_id, self.phases[traffic_light_id], duration))


class OccupancyLanes:
    def getLastStepOccupancy(self, _: str) -> float:
        return 0.0


class NetworkDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.light = DiscoveryLight()
        self.connection = SimpleNamespace(
            trafficlight=self.light,
            lane=OccupancyLanes(),
            simulation=SimpleNamespace(getDeltaT=lambda: 1.0),
        )
        self.manifest = {
            "schema_version": "1.0",
            "profile_id": "test_pressure",
            "discovery": {
                "minimum_adjustable_green_s": 20,
                "expected_controller_ids": ["tls_a", "tls_b", "tls_bad", "tls_fixed"],
                "excluded_controllers": {"tls_fixed": "single movement"},
            },
        }

    def load(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(self.manifest), encoding="utf-8")
            return load_adaptive_signal_set(path, self.connection)

    def test_multi_stage_discovery_and_invalid_fallback(self) -> None:
        loaded = self.load()
        self.assertEqual([signal.tls_id for signal in loaded.signals], ["tls_a", "tls_b"])
        self.assertIn("fewer than two", loaded.fixed_controllers["tls_bad"])
        self.assertEqual(loaded.fixed_controllers["tls_fixed"], "single movement")
        self.assertEqual(len(loaded.signals[1].groups), 3)

    def test_multi_stage_changes_only_green_and_controllers_are_independent(self) -> None:
        first, second = self.load().signals
        first.tick([])
        second.tick([])
        self.light.phases["tls_a"] = 1
        first.tick([])
        second.tick([])
        self.assertEqual(first._phase_seen, 1)
        self.assertEqual(second._phase_seen, 0)
        for phase_index in range(1, 6):
            self.light.phases["tls_b"] = phase_index
            second.tick([])
        changed_phases = [
            phase for tls_id, phase, _duration in self.light.requests
            if tls_id == "tls_b"
        ]
        self.assertEqual(changed_phases, [0, 2, 4])


class CorridorLight:
    def __init__(self, downstream_switch_s: float = 35.0) -> None:
        self.programs = {
            "upstream": [(30, "Grr"), (3, "yrr"), (30, "rGG"), (3, "ryy")],
            "downstream": [(35, "G"), (3, "y"), (45, "r"), (7, "r")],
        }
        self.phases = {"upstream": 0, "downstream": 0}
        self.downstream_switch_s = downstream_switch_s

    def getIDList(self) -> tuple[str, ...]:
        return tuple(self.programs)

    def getProgram(self, _: str) -> str:
        return "0"

    def getAllProgramLogics(self, traffic_light_id: str) -> list:
        return [SimpleNamespace(
            programID="0",
            phases=[
                SimpleNamespace(duration=duration, state=state)
                for duration, state in self.programs[traffic_light_id]
            ],
        )]

    def getControlledLinks(self, traffic_light_id: str) -> list:
        if traffic_light_id == "upstream":
            return [
                [("upstream_in_0", "corridor_0", "via_0")],
                [("upstream_in_1", "other_1", "via_1")],
                [("upstream_in_2", "other_2", "via_2")],
            ]
        return [[("corridor_0", "downstream_out", "via_downstream")]]

    def getPhase(self, traffic_light_id: str) -> int:
        return self.phases[traffic_light_id]

    def getNextSwitch(self, traffic_light_id: str) -> float:
        return self.downstream_switch_s if traffic_light_id == "downstream" else 30.0


class CorridorLanes:
    def __init__(self, occupancy: float = 0.0) -> None:
        self.occupancy = occupancy

    def getLength(self, _: str) -> float:
        return 100.0

    def getMaxSpeed(self, _: str) -> float:
        return 10.0

    def getLastStepOccupancy(self, _: str) -> float:
        return self.occupancy


class CorridorGuardTests(unittest.TestCase):
    def make_signal(
        self, *, downstream_switch_s: float = 35.0, occupancy: float = 0.0
    ) -> AdaptiveSignal:
        spec = {
            "intersection_id": "upstream",
            "traffic_light_id": "upstream",
            "program_id": "0",
            "strategy": "pressure_v1",
            "green_budget_s": 60,
            "groups": [
                {"group_id": "phase_0", "phase_index": 0, "link_indices": [0],
                 "min_green_s": 20, "max_green_s": 40},
                {"group_id": "phase_2", "phase_index": 2, "link_indices": [1, 2],
                 "min_green_s": 20, "max_green_s": 40},
            ],
            "phases": [
                {"index": 0, "state": "Grr", "duration_s": 30, "group_id": "phase_0"},
                {"index": 1, "state": "yrr", "duration_s": 3},
                {"index": 2, "state": "rGG", "duration_s": 30, "group_id": "phase_2"},
                {"index": 3, "state": "ryy", "duration_s": 3},
            ],
            "corridor_guards": [{
                "guard_id": "verified_corridor",
                "upstream_phase_index": 0,
                "minimum_receiving_space_m": 7.5,
                "movements": [{
                    "upstream_link_index": 0,
                    "receiving_lane_id": "corridor_0",
                    "downstream_traffic_light_id": "downstream",
                    "downstream_link_index": 0,
                }],
            }],
        }
        connection = SimpleNamespace(
            trafficlight=CorridorLight(downstream_switch_s),
            lane=CorridorLanes(occupancy),
            simulation=SimpleNamespace(
                getTime=lambda: 0.0,
                getDeltaT=lambda: 1.0,
            ),
        )
        return AdaptiveSignal(spec, connection)

    @staticmethod
    def extension_plan() -> CyclePlan:
        return CyclePlan(
            "upstream",
            {"phase_0": 32.0, "phase_2": 28.0},
            {"phase_0": 32.0, "phase_1": 3.0, "phase_2": 28.0, "phase_3": 3.0},
            ("phase_0", "phase_1", "phase_2", "phase_3"),
            {"phase_0": 2, "phase_2": 0},
            "test_extension",
            {"phase_0": 1.0, "phase_2": 0.0},
        )

    def test_downstream_red_suppresses_extension_and_preserves_budget(self) -> None:
        signal = self.make_signal(downstream_switch_s=35.0)
        plan, outcomes = signal._apply_corridor_guards(
            self.extension_plan(), {"phase_0": 30.0, "phase_2": 30.0}
        )
        self.assertEqual(plan.green_durations_s, {"phase_0": 30.0, "phase_2": 30.0})
        self.assertEqual(sum(plan.green_durations_s.values()), 60.0)
        self.assertIn("downstream_not_green", outcomes[0]["reasons"][0])

    def test_downstream_green_with_storage_keeps_extension(self) -> None:
        signal = self.make_signal(downstream_switch_s=50.0)
        original = self.extension_plan()
        plan, outcomes = signal._apply_corridor_guards(
            original, {"phase_0": 30.0, "phase_2": 30.0}
        )
        self.assertIs(plan, original)
        self.assertEqual(outcomes, [])

    def test_insufficient_storage_suppresses_extension(self) -> None:
        signal = self.make_signal(downstream_switch_s=50.0, occupancy=95.0)
        plan, outcomes = signal._apply_corridor_guards(
            self.extension_plan(), {"phase_0": 30.0, "phase_2": 30.0}
        )
        self.assertEqual(plan.green_durations_s["phase_0"], 30.0)
        self.assertIn("insufficient_storage", outcomes[0]["reasons"][0])

    def test_unverified_lane_mapping_is_rejected(self) -> None:
        signal = self.make_signal()
        signal.spec["corridor_guards"][0]["movements"][0]["receiving_lane_id"] = "unknown"
        with self.assertRaisesRegex(ValueError, "does not connect"):
            signal._validate_corridor_guards()

    def test_prediction_crossing_green_boundary_is_constrained(self) -> None:
        signal = self.make_signal(downstream_switch_s=41.0)
        plan, outcomes = signal._apply_corridor_guards(
            self.extension_plan(), {"phase_0": 30.0, "phase_2": 30.0}
        )
        self.assertEqual(plan.green_durations_s["phase_0"], 30.0)
        self.assertTrue(outcomes)


class PressurePlanQuantizationTests(unittest.TestCase):
    @staticmethod
    def config(
        baselines: tuple[float, ...], *, max_change_s: float = 6.0
    ) -> CycleConfig:
        groups = tuple(
            GreenGroup(f"g{index}", f"p{index}", 20.0, 54.0)
            for index in range(len(baselines))
        )
        return CycleConfig(
            "quantized",
            groups,
            (FixedPhase("clearance", 6.0),),
            sum(baselines),
            tuple([group.phase_id for group in groups] + ["clearance"]),
            max_change_s=max_change_s,
        )

    @staticmethod
    def plan(values: tuple[float, ...]) -> CyclePlan:
        greens = {f"g{index}": value for index, value in enumerate(values)}
        phases = {f"p{index}": value for index, value in enumerate(values)}
        phases["clearance"] = 6.0
        return CyclePlan(
            "quantized",
            greens,
            phases,
            tuple([f"p{index}" for index in range(len(values))] + ["clearance"]),
            {f"g{index}": 0 for index in range(len(values))},
            "fractional_pressure",
        )

    def test_joint_rounding_of_42_6_and_41_4_preserves_budget(self) -> None:
        config = self.config((42.0, 42.0))
        result = quantize_pressure_plan(
            self.plan((42.6, 41.4)), config, {"g0": 42.0, "g1": 42.0}, 1.0
        )
        self.assertEqual(result.green_durations_s, {"g0": 43.0, "g1": 41.0})
        self.assertEqual(sum(result.green_durations_s.values()), 84.0)
        self.assertEqual(result.phase_durations_s["clearance"], 6.0)

    def test_joint_rounding_of_33_33_and_32_67(self) -> None:
        config = self.config((33.0, 33.0))
        result = quantize_pressure_plan(
            self.plan((33.33, 32.67)), config, {"g0": 33.0, "g1": 33.0}, 1.0
        )
        self.assertEqual(result.green_durations_s, {"g0": 33.0, "g1": 33.0})
        self.assertEqual(sum(result.green_durations_s.values()), 66.0)

    def test_three_stage_rounding_is_joint_and_budget_exact(self) -> None:
        config = self.config((27.0, 27.0, 27.0))
        result = quantize_pressure_plan(
            self.plan((27.4, 26.4, 27.2)),
            config,
            {"g0": 27.0, "g1": 27.0, "g2": 27.0},
            1.0,
        )
        self.assertEqual(result.green_durations_s, {"g0": 28.0, "g1": 26.0, "g2": 27.0})
        self.assertEqual(sum(result.green_durations_s.values()), 81.0)

    def test_repeated_cycles_preserve_slew_and_minimum_service(self) -> None:
        config = self.config((42.0, 42.0), max_change_s=1.0)
        first = quantize_pressure_plan(
            self.plan((48.0, 36.0)), config, {"g0": 43.0, "g1": 41.0}, 1.0
        )
        second = quantize_pressure_plan(
            self.plan((48.0, 36.0)), config, first.green_durations_s, 1.0
        )
        self.assertEqual(first.green_durations_s, {"g0": 44.0, "g1": 40.0})
        self.assertEqual(second.green_durations_s, {"g0": 45.0, "g1": 39.0})
        self.assertTrue(all(value >= 20.0 for value in second.green_durations_s.values()))
        self.assertEqual(sum(second.green_durations_s.values()), 84.0)


if __name__ == "__main__":
    unittest.main()
