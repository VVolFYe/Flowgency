"""Parked-vehicle rule in gate mode (scene ``parked_max_travel_px``). Pure: no media, no model, no tracker."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from backend.vision.counting import TrackedBox
from backend.vision.gate_pipeline import TrackedFrame, parked_details, parked_track_ids, track_travel, without_tracks
from backend.vision.gates import run_gates
from backend.vision.scene import load_scene, save_scene
from tests.test_vision_scene import scene

FPS = 10.0
FRAMES = 140  # every exit happens before the last whole second (t_s 13)


def _line(a: tuple[float, float], b: tuple[float, float], step: float = 6.0) -> list[tuple[float, float]]:
    n = max(1, round(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 / step))
    return [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(1, n + 1)]


def _route(*waypoints: tuple[float, float]) -> list[tuple[float, float]]:
    out = [waypoints[0]]
    for a, b in zip(waypoints, waypoints[1:]):
        out += _line(a, b)
    return out


def _jitter(f: int, amp: float) -> float:
    return amp * ((f * 7) % 5 - 2) / 2  # deterministic -amp .. +amp


# Fixture scene (tests/test_vision_scene.py): north inbound lanes x 150-195, far gate y 0-40, stop gate y 120-155.
PARKED_IN_FAR = {f: (172 + _jitter(f, 3), 20 + _jitter(f + 1, 3)) for f in range(FRAMES)}
PARKED_IN_STOP = {f: (172 + _jitter(f, 4), 137) for f in range(FRAMES)}
PARKED_ROADSIDE = {f: (60, 330 + _jitter(f, 2)) for f in range(FRAMES)}
# Waits at the red light on the north approach for 8 s (80 of 140 frames), then turns left into the east arm.
_RED = _route((172, 100), (172, 160), (195, 200), (240, 226), (330, 228))
RED_LIGHT = {f: (172 + _jitter(f, 2), 100) if f < 80 else _RED[min(f - 80, len(_RED) - 1)]
             for f in range(FRAMES) if f < 80 or f - 80 < len(_RED)}
# Parked left of the north far gate for 6 s, pulls into the lane through the far gate, then drives to the east exit.
_PULL = _route((130, 20), (185, 20), (185, 160), (210, 200), (250, 226), (330, 228))
PULLS_OUT = {f: (130 + _jitter(f, 2), 20) if f < 60 else _PULL[f - 60]
             for f in range(FRAMES) if f < 60 or f - 60 < len(_PULL)}

TRACKS = {1: PARKED_IN_FAR, 2: PARKED_IN_STOP, 3: PARKED_ROADSIDE, 4: RED_LIGHT, 5: PULLS_OUT}


def tracked_frames(tracks: dict[int, dict[int, tuple[float, float]]]) -> list[TrackedFrame]:
    out = []
    for f in range(FRAMES):
        boxes = tuple(TrackedBox(tid, "vehicle", 0.9, (p[0] - 7, p[1] - 12, p[0] + 7, p[1] + 12))
                      for tid, path in sorted(tracks.items()) if (p := path.get(f)) is not None)
        out.append(TrackedFrame(f, boxes))
    return out


def run(tracked: list[TrackedFrame], max_travel_px: float | None):
    s = scene(parked_max_travel_px=max_travel_px)
    parked = parked_track_ids(track_travel(tracked, s.counting_point, s.frame_size), s.parked_max_travel_px)
    counted = without_tracks(tracked, parked)
    points = [(tf.frame, tf.points(s.counting_point)) for tf in counted]
    return parked, run_gates(s, points, fps=FPS, frame_count=FRAMES, model_id="yolo11s_visdrone")


class ParkedRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tracked = tracked_frames(TRACKS)

    def test_only_never_moving_tracks_are_parked(self) -> None:
        parked, _ = run(self.tracked, 30.0)
        self.assertEqual(parked, {1, 2, 3})  # the red-light car (4) and the pull-out car (5) move within the clip

    def test_parked_tracks_never_reach_initial_state_events_or_counts(self) -> None:
        _, r = run(self.tracked, 30.0)
        self.assertEqual(r.initial.approach_tracks["north"], (4,))  # the red-light car is counted at the start
        self.assertEqual(r.initial.junction_tracks, ())
        self.assertTrue({1, 2, 3}.isdisjoint(t.track_id for t in r.triggers))
        self.assertTrue({1, 2, 3}.isdisjoint(e["track_id"] for e in r.events))
        self.assertEqual(sorted((e["track_id"], e["event"], e["arm"]) for e in r.events), [
            (4, "intersection_entered", "north"), (4, "intersection_exited", "east"),
            (5, "approach_entered", "north"), (5, "intersection_entered", "north"), (5, "intersection_exited", "east"),
        ])
        self.assertEqual(r.counts[-1]["approaches"]["north"],
                         {"vehicles_on_approach": 0, "entered_total": 1, "discharged_total": 2})
        self.assertEqual(r.counts[-1]["in_intersection"], 0)
        self.assertEqual(r.clamps, [])

    def test_pull_out_car_counts_from_when_it_starts_moving(self) -> None:
        _, r = run(self.tracked, 30.0)
        first = min(e["frame"] for e in r.events if e["track_id"] == 5)
        self.assertGreaterEqual(first, 60)  # nothing while it sat in the parking spot
        self.assertEqual([e["origin_arm"] for e in r.events if e["event"] == "intersection_exited"], ["north", "north"])

    def test_rule_off_keeps_the_previous_behaviour(self) -> None:
        parked, r = run(self.tracked, None)
        self.assertEqual(parked, set())
        self.assertEqual(r.initial.approach_tracks["north"], (1, 2, 4))
        # the car parked inside the stop gate fakes a discharge: exactly what the rule prevents
        self.assertIn((2, "intersection_entered"), [(e["track_id"], e["event"]) for e in r.events])

    def test_threshold_is_inclusive_and_whole_clip(self) -> None:
        travel = {1: 30.0, 2: 30.5, 3: 0.0}
        self.assertEqual(parked_track_ids(travel, 30.0), {1, 3})
        self.assertEqual(parked_track_ids(travel, None), set())
        # moving 6 px per frame for 4 frames (24 px) and stopping: a short window would call this parked too
        short = tracked_frames({7: {f: (100 + 6 * min(f, 4), 300) for f in range(FRAMES)}})
        self.assertEqual(parked_track_ids(track_travel(short, "center"), 30.0), {7})
        longer = tracked_frames({7: {f: (100 + 6 * min(f, 6), 300) for f in range(FRAMES)}})
        self.assertEqual(parked_track_ids(track_travel(longer, "center"), 30.0), set())

    def test_parked_details_name_region_and_gates(self) -> None:
        s = scene(parked_max_travel_px=30.0)
        travel = track_travel(self.tracked, s.counting_point, s.frame_size)
        details = {d["track_id"]: d for d in parked_details(self.tracked, {1, 2, 3}, travel, s, FPS)}
        self.assertEqual(details[1]["gates"], ["north_in.far"])
        self.assertEqual(details[2]["gates"], ["north_in.stop"])
        self.assertEqual((details[1]["region"], details[3]["region"], details[3]["gates"]), ("north", None, []))
        self.assertEqual((details[3]["frames"], details[3]["first_s"], details[3]["last_s"]), (FRAMES, 0.0, 13.9))

    def test_queued_car_clipped_at_the_frame_edge_is_not_parked(self) -> None:
        # Rolls in from the top edge into the north far gate and stops in the queue with its box still clipped
        # (top at y 0): the clipped centre moves only ~12 px, which alone would look parked.
        def box(f: int) -> tuple[float, float, float, float]:
            bottom = min(8 + 4 * (f - 20), 32)  # arrives at frame 20 (after the initial window), then stops
            return (165.0, 0.0, 179.0, float(bottom))
        tracked = [TrackedFrame(f, (TrackedBox(9, "vehicle", 0.9, box(f)),) if f >= 20 else ()) for f in range(FRAMES)]
        self.assertLess(track_travel(tracked, "center")[9], 25.0)
        self.assertNotIn(9, track_travel(tracked, "center", (400, 400)))  # no fully visible box: unknown
        parked, r = run(tracked, 25.0)
        self.assertEqual(parked, set())
        self.assertEqual([(e["track_id"], e["event"], e["arm"]) for e in r.events], [(9, "approach_entered", "north")])

    def test_edge_boxes_are_skipped_but_visible_ones_still_measure(self) -> None:
        # parked against the left border for a while (clipped), then fully visible and still: parked
        boxes = [(0.0, 300.0, 10.0 + (f % 3), 320.0) if f < 50 else (4.0, 300.0, 18.0, 320.0) for f in range(FRAMES)]
        tracked = [TrackedFrame(f, (TrackedBox(4, "vehicle", 0.9, b),)) for f, b in enumerate(boxes)]
        self.assertEqual(track_travel(tracked, "center", (400, 400)), {4: 0.0})


class ParkedSceneFieldTests(unittest.TestCase):
    def test_default_off_positive_only_and_round_trips(self) -> None:
        self.assertIsNone(scene().parked_max_travel_px)
        for bad in (0, -5):
            with self.assertRaises(ValidationError):
                scene(parked_max_travel_px=bad)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            save_scene(scene(parked_max_travel_px=30), path)
            self.assertEqual(json.loads(path.read_text())["parked_max_travel_px"], 30.0)
            self.assertEqual(load_scene(path).parked_max_travel_px, 30.0)


if __name__ == "__main__":
    unittest.main()
