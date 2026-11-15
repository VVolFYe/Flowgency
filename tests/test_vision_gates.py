"""Gate rule and the causal gate engine: warm-up, joins, leaves, counts (pure; synthetic tracks, no media)."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from backend.models.gates import GateCounts, GateCountsInput, GateEvent, GateEventInput
from backend.vision.gates import TrackPoint, detect_triggers, run_gates
from tests.test_vision_scene import GATES, scene

FPS = 10.0
# Path tests: warm-up at frame 5 and confirmation after 2 observations, unless a test overrides them.
FAST = {"warmup_s": 0.5, "min_track_frames": 2}


def frames_of(paths: dict[int, dict[int, tuple[float, float]]], n: int) -> list[tuple[int, list[TrackPoint]]]:
    """``{track_id: {frame: point}}`` -> per-frame track points for frames 0..n-1."""
    return [(f, [TrackPoint(tid, pts[f]) for tid, pts in sorted(paths.items()) if f in pts]) for f in range(n)]


def line(points: list[tuple[float, float]], start: int) -> dict[int, tuple[float, float]]:
    return {start + i: p for i, p in enumerate(points)}


def run(paths, n=60, gates=None, **overrides):
    s = scene(**{**FAST, **({"gates": gates} if gates is not None else {}), **overrides})
    return run_gates(s, frames_of(paths, n), fps=FPS, frame_count=n, model_id="test_model")


def kinds(r) -> list[tuple]:
    return [(e["track_id"], e["event"], e["arm"], e.get("via")) for e in r.events]


def polyline(waypoints: list[tuple[float, float]], step: float = 8.0) -> list[tuple[float, float]]:
    """One point every ``step`` px along the waypoints (one point per frame)."""
    out = [waypoints[0]]
    for (x1, y1), (x2, y2) in zip(waypoints, waypoints[1:]):
        n = max(1, round(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 / step))
        out += [(x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n) for k in range(1, n + 1)]
    return out


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

    def test_left_turner_clipping_a_second_stop_gate_enters_once(self) -> None:
        # South -> west left turn whose curve clips the top-right corner of west_in.stop (x 120-155, y 205-250),
        # as on the youtube clip. Only the first stop trigger is an entry; the second is suppressed and logged.
        from backend.vision.gate_pipeline import run_summary

        r = run({7: line(polyline([(228, 395), (228, 262), (200, 236), (150, 212), (140, 206), (100, 172)]), 5)})
        self.assertEqual(kinds(r), [(7, "approach_entered", "south", "far_gate"), (7, "intersection_entered", "south", None),
                                    (7, "intersection_exited", "west", None)])
        self.assertEqual(r.events[-1]["origin_arm"], "south")
        self.assertEqual(r.origin_null, {})
        suppressed = [t for t in r.triggers if t.suppressed]
        self.assertEqual([(t.track_id, t.gate_id, t.suppressed) for t in suppressed],
                         [(7, "west_in.stop", "already_entered")])
        x, y = suppressed[0].point
        self.assertTrue(120 <= x <= 155 and 205 <= y <= 250)
        last = r.counts[-1]
        self.assertEqual(last["approaches"]["west"]["discharged_total"], 0)
        self.assertEqual(last["approaches"]["south"],
                         {"vehicles_on_approach": 0, "entered_total": 1, "discharged_total": 1, "left_total": 0})
        self.assertEqual(last["in_intersection"], 0)
        self.assertEqual(r.clamps, [])
        summary = run_summary(r, scene(), {})
        entry = summary["suppressed_triggers"][0]
        self.assertEqual((entry["track_id"], entry["gate_id"], entry["reason"], entry["entered_via"]),
                         (7, "west_in.stop", "already_entered", "south_in.stop"))
        self.assertEqual((entry["x"], entry["y"]), (round(x, 1), round(y, 1)))
        self.assertEqual(summary["already_entered_by_gate_pair"], {"south_in.stop -> west_in.stop": 1})
        self.assertEqual(summary["triggers_by_gate"]["west_in.stop"], 0)

    def test_straight_through_vehicle_is_not_suppressed(self) -> None:
        r = run({3: line(polyline([(228, 395), (228, 90)]), 5)})
        self.assertEqual([(e["event"], e["arm"]) for e in r.events],
                         [("approach_entered", "south"), ("intersection_entered", "south"), ("intersection_exited", "north")])
        self.assertEqual(r.events[-1]["origin_arm"], "south")
        self.assertEqual([t.suppressed for t in r.triggers], [None, None, None])
        self.assertEqual(r.clamps, [])


class WarmUpTests(unittest.TestCase):
    """Starting offset at warm-up frame 5, from tracks observed in >= 3 frames by then."""

    def paths(self):
        return {
            1: {f: (170, 80) for f in range(60)},                                    # queued on north
            2: {f: (180, 90) for f in range(4, 60)},                                 # only 2 observations at frame 5
            3: {f: (172, min(5 + 8 * f, 165)) for f in range(60)},                   # crosses north far gate at frame 1
            4: {f: (200, 200) for f in range(60)},                                   # in the junction
            5: {f: (228, 270 - 8 * f) for f in range(23)},                           # crosses south stop at frame 1, exits north
            6: {f: (300, 220) for f in range(3)},                                    # leaves by east_out during warm-up
        }

    def go(self):
        return run(self.paths(), min_track_frames=3)

    def test_offset_from_confirmed_tracks_where_they_are_at_warm_up(self) -> None:
        r = self.go()
        self.assertEqual(r.initial.warmup_frame, 5)
        self.assertEqual(r.initial.approach_tracks, {"north": (1, 3), "east": (), "south": (), "west": ()})
        self.assertEqual(r.initial.junction_tracks, (4, 5))
        self.assertEqual([(t.track_id, t.gate_id) for t in r.triggers if t.suppressed == "warmup"],
                         [(3, "north_in.far"), (5, "south_in.stop"), (6, "east_out")])

    def test_counts_unknown_before_warm_up(self) -> None:
        r = self.go()
        self.assertEqual(r.counts[0]["approaches"], {})   # t_s 0 < warm-up at 0.5 s
        self.assertIsNone(r.counts[0]["in_intersection"])
        for c in r.counts:
            GateCounts.model_validate(c)
            GateCountsInput.model_validate(c)
        self.assertEqual(r.counts[1]["approaches"]["north"],  # t 1.0: track 2 joined at frame 6
                         {"vehicles_on_approach": 3, "entered_total": 1, "discharged_total": 0, "left_total": 0})

    def test_late_confirmed_track_joins_and_offset_tracks_balance(self) -> None:
        r = self.go()
        self.assertEqual(kinds(r), [
            (2, "approach_entered", "north", "region"),      # frame 6: confirmed, never crossed the far gate
            (3, "intersection_entered", "north", None),      # frame 16: discharges an offset vehicle
            (5, "intersection_exited", "north", None),
        ])
        self.assertEqual([e["frame"] for e in r.events], [6, 16, 21])
        self.assertIsNone(r.events[-1]["origin_arm"])
        self.assertEqual(r.origin_null, {"in_junction_at_start": 1})
        self.assertEqual(r.counts[-1]["approaches"]["north"],
                         {"vehicles_on_approach": 2, "entered_total": 1, "discharged_total": 1, "left_total": 0})
        self.assertEqual(r.counts[-1]["in_intersection"], 2)  # 2 initial + track 3 - track 5
        self.assertEqual(r.clamps, [])

    def test_offset_vehicle_far_trigger_after_warm_up_is_suppressed(self) -> None:
        r = run({1: {f: (170, 60) for f in range(8)} | {8: (170, 30), 9: (170, 20), 10: (170, 25)}})
        self.assertEqual([(t.gate_id, t.suppressed) for t in r.triggers], [("north_in.far", "initial_on_approach")])
        self.assertEqual(kinds(r), [(1, "approach_left", "north", "lost")])  # gone after frame 10


class MidApproachTests(unittest.TestCase):
    def test_pull_out_from_a_parking_spot_joins_via_region(self) -> None:
        # parked left of the north lanes (outside every region), pulls out at frame 30, drives north -> east
        path = {f: (120, 60) for f in range(30)} | line(polyline(
            [(120, 60), (172, 60), (172, 160), (200, 200), (250, 220), (300, 228)])[1:], 30)
        r = run({1: path}, n=70)
        self.assertEqual(kinds(r), [(1, "approach_entered", "north", "region"), (1, "intersection_entered", "north", None),
                                    (1, "intersection_exited", "east", None)])
        self.assertGreater(r.events[0]["frame"], 30)
        self.assertEqual(r.events[-1]["origin_arm"], "north")
        self.assertEqual(r.counts[-1]["approaches"]["north"],
                         {"vehicles_on_approach": 0, "entered_total": 1, "discharged_total": 1, "left_total": 0})

    def test_turning_into_a_parking_spot_leaves_via_region(self) -> None:
        path = line(polyline([(172, 5), (172, 60), (120, 60)]), 10)
        path |= {f: (120, 60) for f in range(max(path) + 1, 60)}
        r = run({1: path})
        self.assertEqual(kinds(r), [(1, "approach_entered", "north", "far_gate"), (1, "approach_left", "north", "region")])
        self.assertEqual(r.counts[-1]["approaches"]["north"],
                         {"vehicles_on_approach": 0, "entered_total": 1, "discharged_total": 0, "left_total": 1})
        # left after 3 consecutive observations at least 15 px outside the region (x <= 135)
        outside = [f for f, p in sorted(path.items()) if p[0] <= 135]
        self.assertEqual(r.events[1]["frame"], outside[2])

    def test_queued_on_the_region_edge_does_not_leave(self) -> None:
        # centre 2-12 px outside the left edge (x 150) for 40 frames: within the 15 px margin, still counted
        r = run({1: line(polyline([(152, 5), (152, 60)]), 0) | {f: (148 - (f % 6) * 2, 60) for f in range(10, 50)}})
        self.assertEqual(r.events, [])  # in the warm-up offset; never left (lost would only fire at frame 65)
        self.assertEqual(r.counts[-1]["approaches"]["north"]["vehicles_on_approach"], 1)

    def test_jitter_across_the_region_edge_does_not_leave(self) -> None:
        wobble = {f: ((148 if f % 2 else 152), 60) for f in range(10, 60)}  # one frame out, one in
        r = run({1: line(polyline([(152, 5), (152, 60)]), 0) | wobble})
        self.assertEqual([e["event"] for e in r.events], [])  # in the warm-up offset, never left
        self.assertEqual(r.initial.approach_tracks["north"], (1,))
        self.assertEqual(r.counts[-1]["approaches"]["north"]["vehicles_on_approach"], 1)

    def test_one_approach_entry_per_track(self) -> None:
        path = line(polyline([(172, 5), (172, 60), (120, 60), (120, 61), (172, 70), (172, 160), (200, 200)]), 10)
        r = run({1: path}, n=70)
        self.assertEqual([(e["event"], e.get("via")) for e in r.events],
                         [("approach_entered", "far_gate"), ("approach_left", "region"), ("intersection_entered", None)])
        # it crossed the stop line while not counted: no approach count moves
        self.assertEqual(r.counts[-1]["approaches"]["north"],
                         {"vehicles_on_approach": 0, "entered_total": 1, "discharged_total": 0, "left_total": 1})


class LostAndObstructionTests(unittest.TestCase):
    def test_lost_track_leaves_and_its_new_id_joins(self) -> None:
        first = line(polyline([(172, 5), (172, 80)]), 10) | {f: (172, 80) for f in range(20, 31)}
        second = {f: (172, 82) for f in range(33, 60)}  # the tracker re-identified the queued car
        r = run({1: first, 2: second})
        self.assertEqual(kinds(r), [(1, "approach_entered", "north", "far_gate"), (2, "approach_entered", "north", "region"),
                                    (1, "approach_left", "north", "lost")])
        self.assertEqual([e["frame"] for e in r.events][1:], [34, 46])  # lost after 1.5 s = 15 frames unseen
        by_t = {c["t_s"]: c["approaches"]["north"]["vehicles_on_approach"] for c in r.counts if c["approaches"]}
        self.assertEqual((by_t[3.0], by_t[4.0], by_t[5.0]), (1, 2, 1))  # double counted only while undecided

    def test_obstruction_drops_a_long_stationary_track(self) -> None:
        arrive = line(polyline([(172, 5), (172, 80)]), 10)
        still = {f: (172 + (f % 3) * 4, 80 + (f % 2) * 4) for f in range(max(arrive) + 1, 70)}  # jitter < 25 px
        go = line(polyline([(172, 80), (172, 160)])[1:], 70)
        r = run({1: arrive | still | go}, n=100, obstruction_s=3.0)
        self.assertEqual(kinds(r), [(1, "approach_entered", "north", "far_gate"), (1, "approach_left", "north", "obstruction"),
                                    (1, "intersection_entered", "north", None)])
        # the anchor is the first point within 25 px of where it stops: 2 frames before it arrives (8 px/frame)
        self.assertEqual(r.events[1]["frame"] - min(still), 28)
        self.assertEqual(r.counts[-1]["approaches"]["north"],
                         {"vehicles_on_approach": 0, "entered_total": 1, "discharged_total": 0, "left_total": 1})

    def test_creeping_queue_is_not_an_obstruction(self) -> None:
        creep = line(polyline([(172, 5), (172, 30)]), 10)
        creep |= {f: (172, 30 + (f - 14) * 1.0) for f in range(14, 100)}  # 1 px per frame: 10 px/s, 30 px in 3 s
        r = run({1: creep}, n=100, obstruction_s=3.0)
        self.assertEqual([e["event"] for e in r.events], ["approach_entered"])


class ConfirmationTests(unittest.TestCase):
    def test_short_fragment_in_the_far_gate_creates_no_arrival(self) -> None:
        r = run({1: {20: (172, 10), 21: (172, 18), 22: (172, 26)}}, min_track_frames=5)
        self.assertEqual(r.events, [])
        self.assertEqual([(t.gate_id, t.suppressed) for t in r.triggers], [("north_in.far", "unconfirmed")])

    def test_held_far_trigger_applies_when_confirmed(self) -> None:
        path = line(polyline([(172, 5), (172, 100)]), 20)
        r = run({1: path | {f: (172, 100) for f in range(max(path) + 1, 60)}}, min_track_frames=5)
        self.assertEqual(kinds(r), [(1, "approach_entered", "north", "far_gate")])
        self.assertEqual(r.events[0]["frame"], 24)  # 5th observation
        self.assertEqual([(t.frame, t.applied_frame, t.suppressed) for t in r.triggers], [(21, 24, None)])


class CausalityTests(unittest.TestCase):
    def test_output_up_to_t_is_unchanged_when_later_frames_are_removed(self) -> None:
        paths = WarmUpTests().paths()
        paths[10] = {f: (120, 60) for f in range(30)} | line(polyline(
            [(120, 60), (172, 60), (172, 160), (200, 200), (250, 220), (300, 228)])[1:], 30)
        paths[11] = line(polyline([(172, 5), (172, 80)]), 40) | {f: (172, 80) for f in range(50, 61)}
        paths[12] = {f: (172, 82) for f in range(63, 110)}
        paths[13] = line(polyline([(228, 395), (228, 262), (200, 236), (150, 212), (140, 206), (100, 172)]), 70)
        n = 120
        s = scene(**{**FAST, "min_track_frames": 3, "obstruction_s": 4.0})
        full = run_gates(s, frames_of(paths, n), fps=FPS, frame_count=n, model_id="m")
        self.assertGreater(len(full.events), 10)
        for k in (3, 6, 7, 20, 34, 47, 61, 75, 90, 119):
            cut = run_gates(s, frames_of(paths, k), fps=FPS, frame_count=k, model_id="m")
            self.assertEqual(cut.events, [e for e in full.events if e["frame"] <= k - 1], k)
            self.assertEqual(cut.counts, [c for c in full.counts if c["t_s"] <= (k - 1) / FPS], k)


class CountsTests(unittest.TestCase):
    def test_counts_one_line_per_second_with_cumulative_totals(self) -> None:
        r = run({1: line(NORTH_THROUGH_TO_EAST, 10)}, n=45)
        self.assertEqual([c["t_s"] for c in r.counts], [float(s) for s in range(5)])
        by_t = {c["t_s"]: c for c in r.counts}
        self.assertEqual(by_t[1.0]["approaches"]["north"]["entered_total"], 0)  # trigger at frame 11 = 1.1 s
        self.assertEqual(by_t[2.0]["approaches"]["north"],
                         {"vehicles_on_approach": 1, "entered_total": 1, "discharged_total": 0, "left_total": 0})
        self.assertEqual(by_t[3.0]["approaches"]["north"],
                         {"vehicles_on_approach": 0, "entered_total": 1, "discharged_total": 1, "left_total": 0})
        self.assertEqual(by_t[3.0]["in_intersection"], 0)  # entered at 2.1 s, exited at 2.7 s
        for c in r.counts:
            GateCounts.model_validate(c)

    def test_uncounted_track_crossing_the_stop_line_moves_no_approach_count(self) -> None:
        appears_at_stop = {10: (170, 130), 11: (170, 140), 12: (170, 160)}  # 1 observation before its stop trigger
        r = run({1: appears_at_stop}, min_track_frames=3)
        self.assertEqual(kinds(r), [(1, "intersection_entered", "north", None)])
        self.assertEqual(r.counts[-1]["approaches"]["north"],
                         {"vehicles_on_approach": 0, "entered_total": 0, "discharged_total": 0, "left_total": 0})
        self.assertEqual(r.counts[-1]["in_intersection"], 1)
        self.assertEqual(r.clamps, [])

    def test_exit_without_entry_clamps_junction(self) -> None:
        r = run({1: line([(300, 220), (300, 225)], 10)})
        self.assertEqual([(c.quantity, c.raw) for c in r.clamps], [("in_intersection", -1)])
        self.assertEqual(r.counts[-1]["in_intersection"], 0)

    def test_missing_gates_make_values_unknown(self) -> None:
        gates = {k: v for k, v in GATES.items() if k not in ("west_in.far", "east_out")}
        r = run({1: line(NORTH_THROUGH_TO_EAST, 10)}, gates=gates)
        self.assertEqual(set(r.counts[-1]["approaches"]), {"north", "east", "south"})
        self.assertIsNone(r.counts[-1]["in_intersection"])
        self.assertIsNone(r.initial.junction_tracks)

    def test_clip_shorter_than_warm_up_is_all_unknown(self) -> None:
        r = run({1: {f: (170, 80) for f in range(4)}}, n=4)
        self.assertEqual([(c["approaches"], c["in_intersection"]) for c in r.counts], [({}, None)])
        self.assertEqual(r.initial.approach_counts(), {"north": 0, "east": 0, "south": 0, "west": 0})

    def test_invalid_inputs(self) -> None:
        with self.assertRaises(ValueError):
            run_gates(scene(), [], fps=0, frame_count=10, model_id="m")


class ContractModelTests(unittest.TestCase):
    EXAMPLES = [
        {"schema_version": "1.0", "event": "approach_entered", "track_id": 41, "arm": "north", "via": "far_gate",
         "t_s": 9.801, "frame": 235, "model_id": "yolo11s_visdrone"},
        {"schema_version": "1.0", "event": "approach_left", "track_id": 52, "arm": "west", "via": "region",
         "t_s": 36.2, "frame": 868, "model_id": "yolo11s_visdrone"},
        {"schema_version": "1.0", "event": "intersection_exited", "track_id": 41, "arm": "east",
         "origin_arm": None, "t_s": 17.893, "frame": 429, "model_id": "yolo11s_visdrone"},
    ]
    COUNTS = {"schema_version": "1.0", "t_s": 13.0, "approaches": {"north": {
        "vehicles_on_approach": 6, "entered_total": 14, "discharged_total": 7, "left_total": 1}}, "in_intersection": 3,
        "model_id": "yolo11s_visdrone"}

    def test_examples_validate_and_round_trip(self) -> None:
        for example in self.EXAMPLES:
            self.assertEqual(GateEvent.model_validate(example).to_contract_dict(), example)
            GateEventInput.model_validate(example)
        self.assertEqual(GateCounts.model_validate(self.COUNTS).to_contract_dict(), self.COUNTS)

    def test_older_files_without_via_or_left_total_still_validate(self) -> None:
        old_event = {k: v for k, v in self.EXAMPLES[0].items() if k != "via"}
        self.assertEqual(GateEvent.model_validate(old_event).to_contract_dict(), old_event)
        old_counts = {**self.COUNTS, "approaches": {"north": {
            "vehicles_on_approach": 6, "entered_total": 14, "discharged_total": 8}}}
        self.assertEqual(GateCounts.model_validate(old_counts).to_contract_dict(), old_counts)
        GateCountsInput.model_validate(old_counts)

    def test_rejections(self) -> None:
        entered, left, exited = self.EXAMPLES
        for bad in ({**entered, "origin_arm": "west"}, {**entered, "arm": "northbound_in"}, {**entered, "track_id": -1},
                    {**entered, "t_s": -0.1}, {**entered, "extra": 1}, {**entered, "model_id": ""},
                    {**entered, "via": "lost"}, {k: v for k, v in left.items() if k != "via"}, {**left, "via": "far_gate"},
                    {**exited, "via": "region"}, {k: v for k, v in exited.items() if k != "origin_arm"}):
            with self.assertRaises(ValidationError, msg=str(bad)):
                GateEvent.model_validate(bad)
        with self.assertRaises(ValidationError):
            GateCounts.model_validate({"t_s": 1.0, "approaches": {"north": {
                "vehicles_on_approach": -1, "entered_total": 0, "discharged_total": 1}},
                "in_intersection": 0, "model_id": "m"})

    def test_producer_rejects_nested_unknown_fields(self) -> None:
        counts = {"schema_version": "1.0", "t_s": 13.0, "approaches": {"north": {
            "vehicles_on_approach": 6, "entered_total": 14, "discharged_total": 9,
            "future_confidence": 0.9}}, "in_intersection": 3, "model_id": "m"}
        with self.assertRaises(ValidationError):
            GateCounts.model_validate(counts)


class StaticDisplayRuleTests(unittest.TestCase):
    def test_static_only_off_lane_and_still_for_three_seconds(self) -> None:
        from backend.vision.gate_render import is_static

        still = [(f, (60.0 + (f % 2), 330.0)) for f in range(0, 31)]
        self.assertTrue(is_static(still, 30, FPS, None, False))
        self.assertFalse(is_static(still[-20:], 30, FPS, None, False))      # seen for only 2 s
        self.assertFalse(is_static(still, 30, FPS, "north", False))         # on an approach: traffic
        self.assertFalse(is_static(still, 30, FPS, None, True))             # in a gate
        moving = [(f, (60.0 + f, 330.0)) for f in range(0, 31)]
        self.assertFalse(is_static(moving, 30, FPS, None, False))
        stopped_now = [(f, (60.0 + min(f, 5) * 20, 330.0)) for f in range(0, 31)]  # moved 100 px, still for 2.5 s
        self.assertFalse(is_static(stopped_now, 30, FPS, None, False))


if __name__ == "__main__":
    unittest.main()
