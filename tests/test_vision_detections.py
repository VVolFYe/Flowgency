"""Detection post-processing, detector profiles, and the class-flip double-count regression.

No media and no weights: the regression test injects a fake YOLO model into
``VehicleTracker`` and runs the real Ultralytics ByteTrack (skipped when
Ultralytics is not installed).
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from backend.vision.counting import CountingLine, LineCrossingCounter, TrackedBox
from backend.vision.track_filter import DuplicateTrackFilter
from backend.vision.detections import (
    PROFILES,
    agnostic_nms,
    counting_point,
    get_profile,
    merge_vehicle_classes,
    vehicle_class_ids,
)

HAS_ULTRALYTICS = importlib.util.find_spec("ultralytics") is not None
COCO_NAMES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck", 67: "cell phone"}
VISDRONE_NAMES = {0: "pedestrian", 1: "people", 2: "bicycle", 3: "car", 4: "van", 5: "truck", 6: "tricycle",
                  7: "awning-tricycle", 8: "bus", 9: "motor"}


def det(x1, y1, x2, y2, score, cls) -> list[float]:
    return [x1, y1, x2, y2, score, cls]


class AgnosticNmsTests(unittest.TestCase):
    def test_overlapping_boxes_with_different_labels_collapse_to_the_best(self) -> None:
        dets = np.array([det(120, 137, 157, 191, 0.40, 2), det(120, 137, 157, 191, 0.51, 7)], np.float32)
        kept = agnostic_nms(dets)
        self.assertEqual(len(kept), 1)
        self.assertAlmostEqual(float(kept[0, 4]), 0.51, places=5)

    def test_nested_box_with_another_label_is_suppressed(self) -> None:
        # J4 f185: car box 89 % inside the truck box, IoU only 0.35.
        dets = np.array([det(142, 51, 155, 62, 0.40, 2), det(139, 41, 155, 61, 0.31, 7)], np.float32)
        kept = agnostic_nms(dets)
        self.assertEqual(kept[:, 5].tolist(), [2.0])

    def test_adjacent_vehicles_are_kept(self) -> None:
        dets = np.array([det(0, 0, 40, 20, 0.9, 2), det(42, 0, 82, 20, 0.8, 2), det(30, 0, 70, 20, 0.7, 7)], np.float32)
        # The third overlaps both neighbours by IoU 0.2-0.33 < 0.7: a real vehicle, kept.
        self.assertEqual(len(agnostic_nms(dets)), 3)

    def test_empty_and_single(self) -> None:
        self.assertEqual(agnostic_nms(np.zeros((0, 6), np.float32)).shape, (0, 6))
        one = np.array([det(0, 0, 1, 1, 0.5, 2)], np.float32)
        self.assertEqual(len(agnostic_nms(one)), 1)

    def test_merge_relabels_vehicles_and_drops_others(self) -> None:
        ids = vehicle_class_ids(COCO_NAMES, get_profile("yolo11s_coco").vehicle_classes)
        self.assertEqual(ids, [2, 3, 5, 7])
        dets = np.array([
            det(0, 0, 40, 20, 0.9, 2),      # car
            det(0, 0, 40, 20, 0.6, 7),      # same vehicle as truck -> suppressed
            det(100, 0, 110, 30, 0.9, 0),   # person -> dropped
            det(200, 0, 215, 20, 0.8, 1),   # bicycle -> dropped
            det(300, 0, 320, 15, 0.7, 3),   # motorcycle -> vehicle
        ], np.float32)
        merged = merge_vehicle_classes(dets, ids)
        self.assertEqual(merged[:, 5].tolist(), [0.0, 0.0])
        np.testing.assert_allclose(merged[:, 4], [0.9, 0.7], rtol=1e-6)


class ProfileTests(unittest.TestCase):
    def test_profiles_have_their_own_class_lists_and_thresholds(self) -> None:
        self.assertEqual(set(PROFILES), {"yolo11s_coco", "yolo11s_visdrone"})
        self.assertEqual(vehicle_class_ids(VISDRONE_NAMES, get_profile("yolo11s_visdrone").vehicle_classes),
                         [3, 4, 5, 8, 9])
        for profile in PROFILES.values():
            self.assertTrue(0 < profile.conf < 1)
            self.assertEqual(profile.weights, f"{profile.model_id}.pt")

    def test_model_missing_a_listed_class_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            vehicle_class_ids(COCO_NAMES, get_profile("yolo11s_visdrone").vehicle_classes)
        with self.assertRaises(ValueError):
            get_profile("yolo11s")


class CountingPointTests(unittest.TestCase):
    def test_modes(self) -> None:
        self.assertEqual(counting_point((10, 20, 30, 60), "bottom_center"), (20, 60))
        self.assertEqual(counting_point((10, 20, 30, 60), "center"), (20, 40))
        with self.assertRaises(ValueError):
            counting_point((0, 0, 1, 1), "top")

    def test_line_counter_uses_configured_point(self) -> None:
        # Line y=100; a 40px-tall box whose bottom is past the line but centre is not.
        line = CountingLine("southbound_in", (0.0, 100.0), (200.0, 100.0), (100.0, 150.0))
        path = [(50, 90), (50, 110)]  # bottom y
        for mode, expected in (("bottom_center", 1), ("center", 0)):
            counter = LineCrossingCounter([line], mode)
            for frame, (x, y) in enumerate(path):
                counter.update(frame, [TrackedBox(1, "car", 0.8, (x - 10, y - 40, x + 10, y))])
            self.assertEqual(counter.result().counts_by_approach["southbound_in"]["total"], expected, mode)


class _FakeTensor:
    def __init__(self, array: np.ndarray) -> None:
        self.array = array

    def cpu(self) -> _FakeTensor:
        return self

    def numpy(self) -> np.ndarray:
        return self.array


class _FakeResult:
    def __init__(self, dets: np.ndarray) -> None:
        self.boxes = type("B", (), {"data": _FakeTensor(dets)})()


class FakeYolo:
    """Returns what per-class NMS produced in the London cache: one vehicle, two labels."""

    names = COCO_NAMES

    def __init__(self, frames: list[np.ndarray]) -> None:
        self.frames = frames
        self.calls: list[dict] = []
        self.index = 0

    def predict(self, frame, **kwargs):
        self.calls.append(kwargs)
        dets = self.frames[self.index]
        self.index += 1
        return [_FakeResult(dets)]


class DuplicateTrackFilterTests(unittest.TestCase):
    def box(self, tid: int, bbox, conf: float = 0.5) -> TrackedBox:
        return TrackedBox(tid, "car", conf, tuple(float(v) for v in bbox))

    def test_nested_newborn_track_maps_to_visible_original(self) -> None:
        f = DuplicateTrackFilter()
        f.update(0, [self.box(7, (139, 42, 154, 61))])
        out = f.update(1, [self.box(7, (139, 41, 155, 61), 0.31), self.box(13, (142, 51, 155, 62), 0.40)])
        self.assertEqual([(b.track_id, b.bbox) for b in out], [(7, (139.0, 41.0, 155.0, 61.0))])
        out = f.update(2, [self.box(13, (142, 52, 155, 63))])  # only the duplicate is seen
        self.assertEqual([b.track_id for b in out], [7])

    def test_reborn_track_within_gap_maps_to_lost_original(self) -> None:
        f = DuplicateTrackFilter(max_gap=6)
        f.update(92, [self.box(22, (237, 132, 256, 154))])
        out = f.update(94, [self.box(25, (238, 142, 253, 156))])
        self.assertEqual(out[0].track_id, 22)
        self.assertEqual(f.aliases, {25: 22})

    def test_reborn_after_gap_or_elsewhere_is_a_new_vehicle(self) -> None:
        f = DuplicateTrackFilter(max_gap=6)
        f.update(0, [self.box(1, (100, 100, 140, 120))])
        self.assertEqual(f.update(7, [self.box(2, (100, 100, 140, 120))])[0].track_id, 2)
        f.update(8, [self.box(3, (300, 100, 340, 120))])
        self.assertEqual(f.update(9, [self.box(4, (200, 100, 240, 120))])[0].track_id, 4)

    def test_adjacent_vehicles_in_a_queue_stay_separate(self) -> None:
        f = DuplicateTrackFilter()
        f.update(0, [self.box(1, (100, 100, 140, 120))])
        # Bumper to bumper (IoS 0.1) and a car pulling in beside the first (IoS 0.5).
        out = f.update(1, [self.box(1, (100, 100, 140, 120)), self.box(2, (136, 100, 176, 120)),
                           self.box(3, (100, 110, 140, 130))])
        self.assertEqual([b.track_id for b in out], [1, 2, 3])

    def test_original_box_preferred_when_both_ids_visible(self) -> None:
        f = DuplicateTrackFilter()
        f.update(0, [self.box(22, (237, 132, 256, 154))])
        f.update(1, [self.box(25, (238, 142, 253, 156), 0.9)])
        out = f.update(2, [self.box(25, (238, 143, 253, 157), 0.9), self.box(22, (235, 137, 257, 162), 0.3)])
        self.assertEqual([(b.track_id, b.bbox[1]) for b in out], [(22, 137.0)])


FIXTURE = Path(__file__).parent / "fixtures" / "vision_class_flip_detections.json"


@unittest.skipUnless(HAS_ULTRALYTICS, "ultralytics not installed")
class ClassFlipDoubleCountRegression(unittest.TestCase):
    """London demos: one vehicle flipping between a truck box and a nested car box was counted twice.

    Replays the real cached yolo11m detections of the two traced vehicles
    through the real ByteTrack: J3 (box shrank -> new ID; old ID re-activated
    and crossed again) and J4 (nested car box beside the truck box). Before the
    fix each case produced two counts.
    """

    def count(self, case: str) -> tuple[list[int], FakeYolo]:
        from backend.vision.detect_track import VehicleTracker
        from backend.vision.paths import VisionPaths

        data = json.loads(FIXTURE.read_text(encoding="utf-8"))[case]
        frames = [np.array(rows, np.float32).reshape(-1, 6) for rows in data["frames"]]
        line = CountingLine("approach", tuple(data["line"][0]), tuple(data["line"][1]), tuple(data["inbound_point"]))
        fake = FakeYolo(frames)
        with tempfile.TemporaryDirectory() as tmp:
            tracker = VehicleTracker(VisionPaths(Path(tmp)), "yolo11m.pt", conf=0.25, use_cache=False, model=fake)
            counter = LineCrossingCounter([line])
            tracker.begin_clip()
            image = np.zeros((288, 352, 3), np.uint8)
            for index in range(len(frames)):
                counter.update(index, tracker.track(image, index))
            tracker.end_clip()
        return [t.track_id for t in counter.result().counted_tracks], fake

    def test_shrunken_box_and_reactivated_track_counted_once(self) -> None:
        counted, fake = self.count("j3")
        self.assertEqual(len(counted), 1, counted)
        self.assertTrue(all(call.get("agnostic_nms") is True for call in fake.calls))

    def test_nested_car_box_beside_truck_counted_once(self) -> None:
        counted, _ = self.count("j4")
        self.assertEqual(len(counted), 1, counted)


if __name__ == "__main__":
    unittest.main()
