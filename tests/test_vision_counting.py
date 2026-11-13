"""Line-crossing counter geometry (pure; no media, no model)."""

from __future__ import annotations

import unittest

from backend.vision.counting import CountingLine, LineCrossingCounter, TrackedBox

# Horizontal line y=100 from x=50..150; inbound side is below (larger y), i.e.
# vehicles drive down the image towards the intersection.
LINE = CountingLine("southbound_in", (50.0, 100.0), (150.0, 100.0), (100.0, 130.0))


def box_at(track_id: int, x: float, y: float, cls: str = "car", conf: float = 0.8) -> TrackedBox:
    """Box whose bottom-centre contact point is (x, y)."""
    return TrackedBox(track_id, cls, conf, (x - 10, y - 20, x + 10, y))


def run(counter: LineCrossingCounter, path: list[tuple], track_id: int = 1, cls: str = "car"):
    for frame, (x, y) in enumerate(path):
        counter.update(frame, [box_at(track_id, x, y, cls)])
    return counter.result()


class LineGeometryTests(unittest.TestCase):
    def test_side_orientation_follows_inbound_point(self) -> None:
        self.assertEqual(LINE.side((100, 120)), 1)
        self.assertEqual(LINE.side((100, 80)), -1)
        self.assertEqual(LINE.side((100, 100)), 0)
        flipped = CountingLine("x", (150.0, 100.0), (50.0, 100.0), (100.0, 130.0))
        self.assertEqual(flipped.side((100, 120)), 1)

    def test_degenerate_lines_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CountingLine("a", (1.0, 1.0), (1.0, 1.0), (5.0, 5.0))
        with self.assertRaises(ValueError):
            CountingLine("a", (0.0, 0.0), (10.0, 0.0), (5.0, 0.0))


class CounterTests(unittest.TestCase):
    def counter(self) -> LineCrossingCounter:
        return LineCrossingCounter([LINE])

    def test_inbound_crossing_counted(self) -> None:
        result = run(self.counter(), [(100, 60), (100, 90), (100, 110), (100, 140)])
        self.assertEqual(result.counts_by_approach["southbound_in"]["total"], 1)
        self.assertEqual(result.counts_by_approach["southbound_in"]["car"], 1)

    def test_outbound_crossing_ignored(self) -> None:
        self.assertFalse(LINE.crosses_inbound((100, 110), (100, 90)))
        self.assertTrue(LINE.crosses_inbound((100, 90), (100, 110)))
        result = run(self.counter(), [(100, 140), (100, 110), (100, 90), (100, 60)])
        self.assertEqual(result.counts_by_approach["southbound_in"]["total"], 0)

    def test_crossing_outside_segment_extent_ignored(self) -> None:
        result = run(self.counter(), [(200, 60), (200, 90), (200, 110), (200, 140)])
        self.assertEqual(result.counts_by_approach["southbound_in"]["total"], 0)

    def test_crossing_at_segment_endpoint_counted(self) -> None:
        result = run(self.counter(), [(150, 90), (150, 110)])
        self.assertEqual(result.counts_by_approach["southbound_in"]["total"], 1)

    def test_track_counted_once_per_approach(self) -> None:
        path = [(100, 90), (100, 110), (100, 95), (100, 115), (100, 85), (100, 120)]
        result = run(self.counter(), path)
        self.assertEqual(result.counts_by_approach["southbound_in"]["total"], 1)

    def test_track_first_seen_past_line_not_counted(self) -> None:
        # Starts downstream, jitters back across and forward again.
        result = run(self.counter(), [(100, 110), (100, 95), (100, 115), (100, 140)])
        self.assertEqual(result.counts_by_approach["southbound_in"]["total"], 0)

    def test_single_observation_never_counts(self) -> None:
        result = run(self.counter(), [(100, 140)])
        self.assertEqual(result.counts_by_approach["southbound_in"]["total"], 0)
        self.assertIsNone(result.confidence)

    def test_crossing_across_tracker_gap_counted(self) -> None:
        counter = self.counter()
        counter.update(0, [box_at(1, 100, 70)])
        counter.update(1, [])
        counter.update(2, [])
        counter.update(3, [box_at(1, 100, 130)])
        self.assertEqual(counter.result().counts_by_approach["southbound_in"]["total"], 1)

    def test_each_track_counted_independently_per_approach(self) -> None:
        east = CountingLine("eastbound_in", (200.0, 50.0), (200.0, 150.0), (230.0, 100.0))
        counter = LineCrossingCounter([LINE, east])
        for frame, (x, y) in enumerate([(100, 80), (100, 120), (180, 120), (220, 120)]):
            counter.update(frame, [box_at(7, x, y)])
        counter.update(10, [box_at(8, 120, 90)])
        counter.update(11, [box_at(8, 120, 110)])
        result = counter.result()
        self.assertEqual(result.counts_by_approach["southbound_in"]["total"], 2)
        self.assertEqual(result.counts_by_approach["eastbound_in"]["total"], 1)
        self.assertEqual(len(result.counted_tracks), 3)

    def test_majority_class_over_track_life(self) -> None:
        counter = self.counter()
        classes = ["truck", "car", "car", "car", "truck"]
        ys = [70, 90, 110, 120, 130]
        for frame, (cls, y) in enumerate(zip(classes, ys)):
            counter.update(frame, [box_at(1, 100, y, cls)])
        counts = counter.result().counts_by_approach["southbound_in"]
        self.assertEqual(counts["car"], 1)
        self.assertEqual(counts["truck"], 0)
        self.assertEqual(counts["total"], 1)
        self.assertEqual(set(counts), {"car", "motorcycle", "bus", "truck", "bicycle", "total"})

    def test_majority_tie_broken_by_confidence(self) -> None:
        counter = self.counter()
        counter.update(0, [box_at(1, 100, 80, "bus", 0.9)])
        counter.update(1, [box_at(1, 100, 120, "truck", 0.5)])
        self.assertEqual(counter.result().counted_tracks[0].class_name, "bus")

    def test_confidence_is_mean_of_counted_track_means(self) -> None:
        counter = self.counter()
        counter.update(0, [box_at(1, 100, 80, conf=0.6), box_at(2, 100, 80, conf=0.9)])
        counter.update(1, [box_at(1, 100, 120, conf=0.8), box_at(3, 300, 300, conf=0.1)])
        # Track 1 counted (mean 0.7); track 2 never crosses; track 3 off-line.
        self.assertAlmostEqual(counter.result().confidence, 0.7)

    def test_unknown_class_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.counter().update(0, [box_at(1, 100, 80, "person")])


if __name__ == "__main__":
    unittest.main()
