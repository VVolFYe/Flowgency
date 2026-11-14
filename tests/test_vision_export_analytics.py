"""Vision analytics export on the committed youtube_30s gate-mode sample."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.models.gates import GateCounts, GateEvent
from backend.vision import export_analytics

SAMPLE = Path(__file__).resolve().parents[1] / "backend" / "vision" / "samples" / "youtube_30s"


class VisionExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.counts = export_analytics.read_jsonl(SAMPLE / "counts.jsonl", GateCounts)
        cls.events = export_analytics.read_jsonl(SAMPLE / "events.jsonl", GateEvent)
        cls.temporary = tempfile.TemporaryDirectory()
        out = Path(cls.temporary.name) / "youtube_30s.json"
        index = Path(cls.temporary.name) / "index.json"
        with mock.patch("builtins.print"):
            export_analytics.main([
                "--counts", str(SAMPLE / "counts.jsonl"), "--events", str(SAMPLE / "events.jsonl"),
                "--out", str(out), "--label", "Clip 30 s", "--index", str(index),
            ])
        cls.document = json.loads(out.read_text(encoding="utf-8"))
        cls.index = json.loads(index.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_source_and_index(self) -> None:
        source = self.document["source"]
        self.assertEqual(self.document["kind"], "vision")
        self.assertEqual(source["label"], "Clip 30 s")
        self.assertEqual(source["duration_s"], 30.0)
        self.assertAlmostEqual(source["fps"], 23.976, delta=0.01)
        self.assertEqual(source["model_id"], "yolo11s_visdrone")
        self.assertEqual(source["sample_readme"], "backend/vision/samples/youtube_30s/README.md")
        self.assertEqual(self.index, [{"id": "youtube_30s", "label": "Clip 30 s",
                                       "kind": "vision", "file": "youtube_30s.json"}])

    def test_timeseries_matches_counts(self) -> None:
        series = self.document["timeseries"]
        self.assertEqual(len(series["t_s"]), 31)
        self.assertEqual(self.document["arms"], ["north", "east", "south", "west"])
        for arm in self.document["arms"]:
            self.assertEqual(series["vehicles_on_approach"][arm],
                             [row.approaches[arm].vehicles_on_approach for row in self.counts])
        self.assertEqual(series["in_intersection"], [row.in_intersection for row in self.counts])

    def test_flow_windows_sum_to_cumulative_totals(self) -> None:
        windows = self.document["flow_per_minute"]
        self.assertEqual(len(windows), 1)
        self.assertTrue(windows[0]["partial"])
        last = self.counts[-1]
        for arm, totals in self.document["totals"].items():
            self.assertEqual(totals["entered"], last.approaches[arm].entered_total)
            self.assertEqual(totals["discharged"], last.approaches[arm].discharged_total)
            self.assertEqual(sum(window["entered"][arm] for window in windows), totals["entered"])
            self.assertEqual(sum(window["discharged"][arm] for window in windows), totals["discharged"])
            self.assertEqual(totals["peak_vehicles_on_approach"],
                             max(row.approaches[arm].vehicles_on_approach for row in self.counts))

    def test_turning_matrix_counts_every_exit_and_unknown_origins(self) -> None:
        exits = [event for event in self.events if event.event == "intersection_exited"]
        matrix = self.document["turning_matrix"]
        self.assertEqual(matrix["origins"][-1], "unknown")
        self.assertEqual(matrix["total_exits"], len(exits))
        self.assertEqual(sum(sum(row.values()) for row in matrix["counts"].values()), len(exits))
        unknown = sum(event.origin_arm is None for event in exits)
        self.assertGreater(unknown, 0)
        self.assertEqual(matrix["unknown_origin_exits"], unknown)

    def test_multi_minute_windows_use_cumulative_differences(self) -> None:
        def row(t: float, entered: int) -> GateCounts:
            return GateCounts(t_s=t, model_id="m", in_intersection=None, approaches={
                "north": {"vehicles_on_approach": 0, "entered_total": entered, "discharged_total": 0}})
        counts = [row(float(t), t // 10) for t in range(0, 131)]
        windows = export_analytics.flow_per_minute(counts, ["north"])
        self.assertEqual([w["entered"]["north"] for w in windows], [6, 6, 1])
        self.assertEqual([w["partial"] for w in windows], [False, False, True])

    def test_limitations_cover_offset_and_top_down_model(self) -> None:
        text = " ".join(self.document["limitations"])
        self.assertIn("first 0.5 s", text)
        self.assertIn("VisDrone", text)


if __name__ == "__main__":
    unittest.main()
