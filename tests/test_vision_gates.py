"""Gate rule, events, initial state, counts, and clamping (pure; synthetic tracks, no media)."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from backend.models.gates import GateCounts, GateEvent
from backend.vision.gates import TrackPoint, detect_triggers, run_gates
from tests.test_vision_scene import GATES, scene

FPS = 10.0  # initial window = 5 frames, stable = observed in >= 4 of them


def frames_of(paths: dict[int, dict[int, tuple[float, float]]], n: int) -> list[tuple[int, list[TrackPoint]]]:
    """``{track_id: {frame: point}}`` -> per-frame track points for frames 0..n-1."""
    return [(f, [TrackPoint(tid, pts[f]) for tid, pts in sorted(paths.items()) if f in pts]) for f in range(n)]


def line(points: list[tuple[float, float]], start: int) -> dict[int, tuple[float, float]]:
    return {start + i: p for i, p in enumerate(points)}


def run(paths, n=60, gates=None, **kw):
    s = scene(gates=gates) if gates is not None else scene()
    return run_gates(s, frames_of(paths, n), fps=FPS, frame_count=n, model_id="test_model", **kw)


NORTH_THROUGH_TO_EAST = [(170, y) for y in range(20, 160, 10)] + [(200, 200), (250, 220), (300, 225), (300, 228)]


class GateRuleTests(unittest.TestCase):
    def test_single_trigger_while_parked_inside(self) -> None:
        triggers = detect_triggers(scene(), frames_of({1: {f: (170, 20) for f in range(10, 30)}}, 30))
        self.assertEqual([(t.track_id, t.gate_id, t.frame) for t in triggers], [(1, "north_in.far", 11)])

    def test_one_frame_inside_is_not_enough(self) -> None:
        one_frame = {1: {10: (170, 20), 11: (170, 60), 12: (170, 70)}}
        self.assertEqual(detect_triggers(scene(), frames_of(one_frame, 20)), [])

    def test_two_of_last_three_frames_tolerates_one_miss(self) -> None:
        unobserved = {1: {10: (170, 20), 12: (170, 20)}}              # tracker missed frame 11
        self.assertEqual([t.frame for t in detect_triggers(scene(), frames_of(unobserved, 20))], [12])
        outside = {1: {10: (170, 20), 11: (170, 45), 12: (170, 25)}}   # jittered out for frame 11
        self.assertEqual([t.frame for t in detect_triggers(scene(), frames_of(outside, 20))], [12])
        consecutive = {1: {10: (170, 20), 11: (170, 25)}}
        self.assertEqual([t.frame for t in detect_triggers(scene(), frames_of(consecutive, 20))], [11])

    def test_two_misses_reset_the_window(self) -> None:
        spread = {1: {10: (170, 20), 13: (170, 20), 16: (170, 20), 17: (170, 60)}}
        self.assertEqual(detect_triggers(scene(), frames_of(spread, 20)), [])
        late = {1: {10: (170, 20), 13: (170, 20), 15: (170, 20)}}      # 13 and 15 are 2 of 13..15
        self.assertEqual([t.frame for t in detect_triggers(scene(), frames_of(late, 20))], [15])

    def test_window_is_configurable(self) -> None:
        path = {1: {10: (170, 20), 12: (170, 20), 13: (170, 20), 14: (170, 20)}}
        frames = frames_of(path, 20)
        self.assertEqual([t.frame for t in detect_triggers(scene(), frames, min_inside=2, window=2)], [13])
        self.assertEqual([t.frame for t in detect_triggers(scene(), frames, min_inside=3, window=3)], [14])
        self.assertEqual([t.frame for t in detect_triggers(scene(), frames, min_inside=3, window=4)], [13])
        self.assertEqual([t.frame for t in detect_triggers(scene(), frames, min_inside=1, window=1)], [10])
        strict = scene(gate_min_inside=3, gate_window_frames=3)
        self.assertEqual([t.frame for t in detect_triggers(strict, frames)], [14])
        with self.assertRaises(ValueError):
            detect_triggers(scene(), frames, min_inside=3, window=2)

    def test_boundary_counts_as_inside(self) -> None:
        on_edge = {1: {10: (150, 20), 11: (195, 40)}}
        self.assertEqual([t.frame for t in detect_triggers(scene(), frames_of(on_edge, 20))], [11])

    def test_track_passing_far_stop_and_out(self) -> None:
        r = run({1: line(NORTH_THROUGH_TO_EAST, 10)})
        self.assertEqual([(e["event"], e["arm"], e["frame"]) for e in r.events], [
            ("approach_entered", "north", 11),
            ("intersection_entered", "north", 21),
            ("intersection_exited", "east", 27),  # inside east_out at frames 26 and 27
        ])
        self.assertEqual(r.events[-1]["origin_arm"], "north")
        self.assertNotIn("origin_arm", r.events[0])
        self.assertEqual(r.events[0]["t_s"], 1.1)
        self.assertEqual(r.events[0]["model_id"], "test_model")

    def test_frames_must_increase(self) -> None:
        with self.assertRaises(ValueError):
            detect_triggers(scene(), [(3, []), (3, [])])


class OriginTests(unittest.TestCase):
    def test_origin_null_when_track_broken(self) -> None:
        before = line([(170, y) for y in range(100, 160, 10)], 10)      # track 1 enters north, then lost
        after = line([(230, 200), (300, 220), (300, 225)], 20)           # track 2 exits east
        r = run({1: before, 2: after})
        exit_ = [e for e in r.events if e["event"] == "intersection_exited"]
        self.assertEqual(len(exit_), 1)
        self.assertIsNone(exit_[0]["origin_arm"])
        self.assertEqual(exit_[0]["track_id"], 2)
        self.assertEqual(r.origin_null, {"no_entry_seen": 1})

    def test_entries_from_two_arms_are_ambiguous(self) -> None:
        path = [(170, 130), (170, 140), (130, 220), (130, 230), (100, 170), (100, 175)]
        r = run({1: line(path, 10)})
        self.assertEqual([e["event"] for e in r.events],
                         ["intersection_entered", "intersection_entered", "intersection_exited"])
        self.assertIsNone(r.events[-1]["origin_arm"])
        self.assertEqual(r.origin_null, {"ambiguous_entry": 1})


class InitialStateTests(unittest.TestCase):
    def paths(self):
        parked = {f: (170, 20) for f in range(0, 60)}                       # inside north far gate
        queued = {f: (170, 80) for f in range(0, 60)}
        leaving = {f: (170, 60 + 10 * f) for f in range(0, 10)} | {10: (300, 225), 11: (300, 228)}  # discharges, exits east
        flicker = {0: (170, 100), 1: (170, 100), 3: (170, 100)}              # 3 of 5 frames: not stable
        in_junction = {f: (200, 200) if f < 8 else (300, 220 + f) for f in range(0, 12)}
        late = {f: (170, 50) for f in range(3, 60)}                          # first seen at frame 3: 2 of 5
        return {1: parked, 2: queued, 3: leaving, 4: flicker, 5: in_junction, 6: late}

    def test_initial_counts_from_stable_tracks(self) -> None:
        r = run(self.paths())
        self.assertEqual(r.initial.window_frames, 5)
        self.assertEqual(r.initial.min_observations, 4)
        self.assertEqual(r.initial.approach_tracks, {"north": (1, 2, 3), "east": (), "south": (), "west": ()})
        self.assertEqual(r.initial.junction_tracks, (5,))

    def test_initial_vehicle_far_trigger_suppressed_and_balances(self) -> None:
        r = run(self.paths())
        suppressed = [(t.track_id, t.gate_id, t.suppressed) for t in r.triggers if t.suppressed]
        self.assertEqual(suppressed, [(1, "north_in.far", "initial_on_approach")])
        self.assertFalse(any(e["track_id"] == 1 for e in r.events))
        exits = [e for e in r.events if e["event"] == "intersection_exited"]
        self.assertEqual([(e["track_id"], e["origin_arm"]) for e in exits], [(5, None), (3, "north")])  # frames 9, 11
        self.assertEqual(r.origin_null, {"in_junction_at_start": 1})
        first, last = r.counts[0], r.counts[-1]
        self.assertEqual(first["approaches"]["north"], {"vehicles_on_approach": 3, "entered_total": 0, "discharged_total": 0})
        self.assertEqual(first["in_intersection"], 1)
        # Track 3 discharged (3 - 1), track 3 and 5 left the junction (1 + 1 - 2).
        self.assertEqual(last["approaches"]["north"]["vehicles_on_approach"], 2)
        self.assertEqual(last["in_intersection"], 0)
        self.assertEqual(r.clamps, [])

    def test_initial_stop_trigger_of_junction_vehicle_suppressed(self) -> None:
        sitting_in_stop_gate_of_east = {f: (262, 170) for f in range(0, 10)}  # stop gate = still on the approach
        r = run({1: sitting_in_stop_gate_of_east})
        self.assertEqual(r.initial.approach_tracks["east"], (1,))
        self.assertEqual([(e["event"], e["arm"]) for e in r.events], [("intersection_entered", "east")])
        self.assertEqual(r.counts[-1]["approaches"]["east"]["vehicles_on_approach"], 0)
        self.assertEqual(r.counts[-1]["in_intersection"], 1)
        # A junction vehicle that clips a stop gate on its way out is not a new entry.
        path = {f: (200, 200) for f in range(0, 6)} | {6: (230, 260), 7: (230, 262), 8: (230, 300)}
        r = run({1: path})
        self.assertEqual([(t.gate_id, t.suppressed) for t in r.triggers], [("south_in.stop", "initial_in_junction")])
        self.assertEqual(r.events, [])


class CountsTests(unittest.TestCase):
    def test_counts_one_line_per_second_with_cumulative_totals(self) -> None:
        r = run({1: line(NORTH_THROUGH_TO_EAST, 10)}, n=45)
        self.assertEqual([c["t_s"] for c in r.counts], [float(s) for s in range(5)])
        by_t = {c["t_s"]: c for c in r.counts}
        self.assertEqual(by_t[1.0]["approaches"]["north"]["entered_total"], 0)  # trigger at frame 11 = 1.1 s
        self.assertEqual(by_t[2.0]["approaches"]["north"], {"vehicles_on_approach": 1, "entered_total": 1, "discharged_total": 0})
        self.assertEqual(by_t[3.0]["approaches"]["north"], {"vehicles_on_approach": 0, "entered_total": 1, "discharged_total": 1})
        self.assertEqual(by_t[3.0]["in_intersection"], 0)  # entered at 2.1 s, exited at 2.7 s
        for c in r.counts:
            GateCounts.model_validate(c)

    def test_clamp_logged_and_formula_not_stateful(self) -> None:
        appears_at_stop = {10: (170, 130), 11: (170, 140), 12: (170, 160)}
        arrivals = {tid: line([(160 + tid, 10), (160 + tid, 20)], 20 + 5 * tid) for tid in (2, 3)}
        r = run({1: appears_at_stop, **arrivals})
        self.assertEqual([(c.quantity, c.arm, c.raw, c.frame) for c in r.clamps],
                         [("vehicles_on_approach", "north", -1, 11)])
        north = [c["approaches"]["north"]["vehicles_on_approach"] for c in r.counts]
        self.assertEqual(north[1], 0)  # raw -1 at 1.1 s, clamped
        self.assertEqual(north[3], 0)  # first arrival at 3.1 s: raw 0
        self.assertEqual(north[4], 1)  # second arrival at 3.6 s: raw 1
        # in_intersection: the stop crossing raised it to 1 without any exit.
        self.assertEqual(r.counts[-1]["in_intersection"], 1)

    def test_exit_without_entry_clamps_junction(self) -> None:
        r = run({1: line([(300, 220), (300, 225)], 10)})
        self.assertEqual([(c.quantity, c.raw) for c in r.clamps], [("in_intersection", -1)])
        self.assertEqual(r.counts[-1]["in_intersection"], 0)

    def test_missing_gates_make_values_unknown(self) -> None:
        gates = {k: v for k, v in GATES.items() if k not in ("west_in.far", "east_out")}
        r = run({1: line(NORTH_THROUGH_TO_EAST, 10)}, gates=gates)
        self.assertEqual(set(r.counts[0]["approaches"]), {"north", "east", "south"})
        self.assertIsNone(r.counts[0]["in_intersection"])
        self.assertIsNone(r.initial.junction_tracks)

    def test_invalid_inputs(self) -> None:
        with self.assertRaises(ValueError):
            run_gates(scene(), [], fps=0, frame_count=10, model_id="m")


class ContractModelTests(unittest.TestCase):
    EXAMPLES = [
        {"schema_version": "1.0", "event": "approach_entered", "track_id": 41, "arm": "north", "t_s": 9.801,
         "frame": 235, "model_id": "yolo11s_visdrone"},
        {"schema_version": "1.0", "event": "intersection_exited", "track_id": 41, "arm": "east",
         "origin_arm": None, "t_s": 17.893, "frame": 429, "model_id": "yolo11s_visdrone"},
    ]

    def test_examples_validate_and_round_trip(self) -> None:
        for example in self.EXAMPLES:
            self.assertEqual(GateEvent.model_validate(example).to_contract_dict(), example)
        counts = {"schema_version": "1.0", "t_s": 13.0, "approaches": {"north": {
            "vehicles_on_approach": 6, "entered_total": 14, "discharged_total": 9}}, "in_intersection": 3,
            "model_id": "yolo11s_visdrone"}
        self.assertEqual(GateCounts.model_validate(counts).to_contract_dict(), counts)

    def test_rejections(self) -> None:
        base = self.EXAMPLES[0]
        for bad in ({**base, "origin_arm": "west"}, {**base, "arm": "northbound_in"}, {**base, "track_id": -1},
                    {**base, "t_s": -0.1}, {**base, "extra": 1}, {**base, "model_id": ""},
                    {k: v for k, v in self.EXAMPLES[1].items() if k != "origin_arm"}):
            with self.assertRaises(ValidationError, msg=str(bad)):
                GateEvent.model_validate(bad)
        with self.assertRaises(ValidationError):
            GateCounts.model_validate({"t_s": 1.0, "approaches": {"north": {
                "vehicles_on_approach": -1, "entered_total": 0, "discharged_total": 1}},
                "in_intersection": 0, "model_id": "m"})


if __name__ == "__main__":
    unittest.main()
