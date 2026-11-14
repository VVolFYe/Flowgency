"""Gate-mode chain on synthetic detections: merge -> ByteTrack -> gates -> validated files.

No media and no model; needs Ultralytics for ByteTrack (skipped otherwise).
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from backend.models.gates import GateCounts, GateEvent
from backend.vision.gates import run_gates
from tests.test_vision_scene import scene

HAS_ULTRALYTICS = importlib.util.find_spec("ultralytics") is not None
VISDRONE_VEHICLES = [3, 4, 5, 8, 9]  # car, van, truck, bus, motor
FPS = 10.0


def car(cx: float, cy: float, score: float = 0.8, cls: int = 3, w: float = 14, h: float = 24) -> list[float]:
    return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, score, cls]


def _polyline(waypoints: list[tuple[float, float]], step: float = 6.0) -> list[tuple[float, float]]:
    """Points every ``step`` px along the waypoints (realistic per-frame motion for ByteTrack)."""
    out = [waypoints[0]]
    for (x1, y1), (x2, y2) in zip(waypoints, waypoints[1:]):
        n = max(1, round(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 / step))
        out += [(x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n) for k in range(1, n + 1)]
    return out


# Southbound car entering at the top (north arm), turning to leave by the east arm.
NORTH_TO_EAST = _polyline([(172, 8), (172, 160), (195, 200), (240, 226), (330, 228)])


def north_to_east(step: int) -> tuple[float, float] | None:
    return NORTH_TO_EAST[step] if 0 <= step < len(NORTH_TO_EAST) else None


@unittest.skipUnless(HAS_ULTRALYTICS, "ultralytics not installed")
class GatePipelineTests(unittest.TestCase):
    def test_track_travel_is_the_counting_point_extent(self) -> None:
        from backend.vision.counting import TrackedBox
        from backend.vision.gate_pipeline import TrackedFrame, track_travel

        frames = [TrackedFrame(f, (TrackedBox(1, "vehicle", 0.9, (f * 3, 0, f * 3 + 10, 10)),
                                   TrackedBox(2, "vehicle", 0.9, (50, 50 + f % 2, 60, 60 + f % 2))))
                  for f in range(5)]
        travel = track_travel(frames, "center")
        self.assertAlmostEqual(travel[1], 12.0)
        self.assertAlmostEqual(travel[2], 1.0)

    def frames(self, flip_labels: bool) -> list[tuple[int, np.ndarray]]:
        out = []
        for f in range(80):
            rows = []
            p = north_to_east(f - 10)
            if p is not None:
                cls = 5 if (flip_labels and f % 2) else 3  # truck/car flips
                rows.append(car(*p, cls=cls))
                if flip_labels and f % 3 == 0:  # nested duplicate box with another label
                    rows.append(car(p[0], p[1] + 4, 0.6, cls=4, w=10, h=12))
            rows.append(car(172, 90, 0.9))  # queued on the north approach the whole clip
            rows.append([10, 10, 14, 30, 0.9, 0])  # pedestrian: ignored
            out.append((f, np.array(rows, np.float32)))
        return out

    def run_chain(self, flip_labels: bool):
        from backend.vision.gate_pipeline import track_all

        tracked = track_all(self.frames(flip_labels), (400, 400), VISDRONE_VEHICLES, conf=0.25)
        s = scene()
        return run_gates(s, [(t.frame, t.points(s.counting_point)) for t in tracked], fps=FPS, frame_count=80,
                         model_id="yolo11s_visdrone"), tracked

    def test_events_and_initial_queue(self) -> None:
        run, tracked = self.run_chain(flip_labels=False)
        self.assertTrue(all(b.class_name == "vehicle" for t in tracked for b in t.boxes))
        self.assertEqual(run.initial.approach_counts()["north"], 1)
        self.assertEqual([(e["event"], e["arm"]) for e in run.events],
                         [("approach_entered", "north"), ("intersection_entered", "north"), ("intersection_exited", "east")])
        self.assertEqual(run.events[-1]["origin_arm"], "north")
        north = run.counts[-1]["approaches"]["north"]
        self.assertEqual(north, {"vehicles_on_approach": 1, "entered_total": 1, "discharged_total": 1})

    def test_label_flips_and_nested_boxes_do_not_double_trigger(self) -> None:
        run, _ = self.run_chain(flip_labels=True)
        self.assertEqual([e["event"] for e in run.events],
                         ["approach_entered", "intersection_entered", "intersection_exited"])

    def test_outputs_validated_and_written(self) -> None:
        from backend.vision.gate_pipeline import write_run_outputs

        run, _ = self.run_chain(flip_labels=False)
        with tempfile.TemporaryDirectory() as tmp:
            summary = write_run_outputs(Path(tmp), run, scene(), {"model_id": "yolo11s_visdrone"})
            events = [json.loads(x) for x in (Path(tmp) / "events.jsonl").read_text().splitlines()]
            counts = [json.loads(x) for x in (Path(tmp) / "counts.jsonl").read_text().splitlines()]
            for e in events:
                GateEvent.model_validate(e)
            for c in counts:
                GateCounts.model_validate(c)
            self.assertEqual(len(counts), 8)
            self.assertEqual(summary["initial"]["vehicles_on_approach"]["north"], 1)
            self.assertEqual(summary["origin_arm_null_share"], 0.0)
            self.assertTrue((Path(tmp) / "gate_run.json").exists())

    def test_process_scene_flags_the_never_moving_initial_track(self) -> None:
        from backend.vision.gate_pipeline import process_scene

        tracked, run, diag = process_scene(scene(), self.frames(False), class_ids=VISDRONE_VEHICLES, conf=0.25,
                                           fps=FPS, model_id="yolo11s_visdrone")
        self.assertEqual(len(tracked), 80)
        self.assertEqual([(e["event"], e["arm"]) for e in run.events],
                         [("approach_entered", "north"), ("intersection_entered", "north"), ("intersection_exited", "east")])
        queued = run.initial.approach_tracks["north"]
        self.assertEqual(diag["static_initial_tracks"], list(queued))  # the car at (172, 90) never moves
        self.assertEqual(diag["static_tracks"], list(queued))
        self.assertEqual(diag["track_ids"], 2)

    def test_sample_keeps_the_first_seconds_consistently(self) -> None:
        from backend.vision.gate_pipeline import write_sample

        run, _ = self.run_chain(flip_labels=False)
        cut = run.events[1]["t_s"]
        with tempfile.TemporaryDirectory() as tmp:
            n_events, n_counts = write_sample(Path(tmp), run, cut)
            events = [json.loads(x) for x in (Path(tmp) / "events.jsonl").read_text().splitlines()]
            counts = [json.loads(x) for x in (Path(tmp) / "counts.jsonl").read_text().splitlines()]
        self.assertEqual(n_events, len(events))
        self.assertEqual(n_counts, len(counts))
        self.assertTrue(all(e["t_s"] <= cut for e in events) and all(c["t_s"] <= cut for c in counts))
        self.assertEqual(events, run.events[:len(events)])
        self.assertEqual(counts, run.counts[:len(counts)])

    def test_refuses_to_write_inside_repo(self) -> None:
        from backend.vision.gate_pipeline import write_jsonl
        from backend.vision.paths import REPO_ROOT

        with self.assertRaises(ValueError):
            write_jsonl(REPO_ROOT / "events.jsonl", [], GateEvent)


if __name__ == "__main__":
    unittest.main()
