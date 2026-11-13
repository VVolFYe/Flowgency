"""Eval-set sampling, ground-truth parsing, labelling state, and metrics (pure)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from backend.vision.evaluation import (
    EvalCandidate,
    Pair,
    PeriodConfig,
    Summary,
    Targets,
    choose_recommendation,
    config_verdict,
    load_ground_truth,
    parse_count_entry,
    render_report,
    sample_eval_set,
)
from backend.vision.label import ClipLabelState, ground_truth_rows, is_complete

ENTER, ESC = 13, 27


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 13, hour, minute, tzinfo=UTC)


class PeriodTests(unittest.TestCase):
    def test_default_utc_periods(self) -> None:
        p = PeriodConfig()
        self.assertEqual(p.classify(at(8)), "day")
        self.assertEqual(p.classify(at(15, 59)), "day")
        self.assertEqual(p.classify(at(16, 0)), "twilight")
        self.assertEqual(p.classify(at(16, 59)), "twilight")
        self.assertEqual(p.classify(at(17)), "night")
        self.assertEqual(p.classify(at(0)), "night")
        self.assertEqual(p.classify(at(6, 59)), "night")
        self.assertEqual(p.classify(at(7, 0)), "twilight")
        self.assertEqual(p.classify(at(7, 59)), "twilight")

    def test_parse_and_validate(self) -> None:
        self.assertEqual(PeriodConfig.parse("09-15", "18-06"), PeriodConfig((9, 15), (18, 6)))
        with self.assertRaises(ValueError):
            PeriodConfig.parse("08-18", "17-07")  # overlap at 17
        with self.assertRaises(ValueError):
            PeriodConfig.parse("08-08", "17-07")


def candidates(camera: str, day: int, night: int, twilight: int = 2) -> list[EvalCandidate]:
    out = []
    for period, n in (("day", day), ("night", night), ("twilight", twilight)):
        out += [EvalCandidate("J1", camera, f"{period}_{i:03d}", "2026-11-13T00:00:00Z", period) for i in range(n)]
    return out


class SamplingTests(unittest.TestCase):
    def test_balanced_and_deterministic(self) -> None:
        pools = {"camA": candidates("camA", 30, 30), "camB": candidates("camB", 30, 30)}
        first = sample_eval_set(pools, 10, 42)
        second = sample_eval_set(pools, 10, 42)
        self.assertEqual(first.rows, second.rows)
        self.assertNotEqual(first.rows, sample_eval_set(pools, 10, 7).rows)
        for cam in pools:
            rows = [r for r in first.rows if r["camera_id"] == cam]
            self.assertEqual(len(rows), 10)
            self.assertEqual(sum(r["period"] == "day" for r in rows), 5)
            self.assertFalse(any(r["period"] == "twilight" for r in rows))
            self.assertEqual(len({r["clip"] for r in rows}), 10)
        self.assertEqual(first.notes, [])

    def test_short_group_filled_and_reported(self) -> None:
        report = sample_eval_set({"camA": candidates("camA", 2, 30)}, 10, 42)
        self.assertEqual(len(report.rows), 10)
        self.assertEqual(sum(r["period"] == "day" for r in report.rows), 2)
        self.assertEqual(sum(r["selection"] == "fill" for r in report.rows), 3)
        self.assertIn("filled 3 from night", report.notes[0])

    def test_both_short_reports_shortfall(self) -> None:
        report = sample_eval_set({"camA": candidates("camA", 2, 3)}, 10, 42)
        self.assertEqual(len(report.rows), 5)
        self.assertTrue(any("short" in n for n in report.notes))


class EntryTests(unittest.TestCase):
    def test_parse_entries(self) -> None:
        self.assertEqual(parse_count_entry("3"), (3, None))
        total, split = parse_count_entry("3 car=2 bus=1")
        self.assertEqual(total, 3)
        self.assertEqual(split, {"car": 2, "motorcycle": 0, "bus": 1, "truck": 0, "bicycle": 0})
        for bad in ("", "-1", "x", "3 car=2", "3 van=3", "3 car=two", "3 car3"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_count_entry(bad)

    def test_label_state_flow(self) -> None:
        state = ClipLabelState(["southbound_in", "westbound_in"])
        for ch in "2 car=2":
            state.key(ord(ch))
        state.key(ENTER)
        self.assertEqual(state.current, 1)
        for ch in "1p":  # 'p' is a playback key, never typed into the entry
            state.key(ord(ch))
        self.assertEqual(state.text, "1")
        state.key(ENTER)
        self.assertEqual(state.action, "save")
        rows = ground_truth_rows(
            {"intersection_id": "J1", "camera_id": "c", "clip": "x", "observed_at_utc": "t", "period": "day"},
            state, now=at(12),
        )
        self.assertEqual([r["total"] for r in rows], [2, 1])
        self.assertEqual(rows[0]["car"], 2)
        self.assertEqual(rows[1]["car"], "")
        self.assertTrue(is_complete([{k: str(v) for k, v in r.items()} for r in rows], ["southbound_in", "westbound_in"]))

    def test_invalid_entry_keeps_approach_and_unusable(self) -> None:
        state = ClipLabelState(["southbound_in"])
        for ch in "3 car=1":
            state.key(ord(ch))
        state.key(ENTER)
        self.assertEqual(state.current, 0)
        self.assertIn("sums", state.message)
        state.key(ord("x"))
        for ch in "lens covered":
            state.key(ord(ch))
        state.key(ENTER)
        self.assertEqual((state.action, state.unusable_reason), ("save", "lens covered"))
        rows = ground_truth_rows({"intersection_id": "J1", "camera_id": "c", "clip": "x", "observed_at_utc": "t",
                                  "period": "night"}, state)
        self.assertEqual(rows[0]["status"], "unusable")

    def test_load_ground_truth(self) -> None:
        rows = [
            {"camera_id": "c", "clip": "a", "approach_id": "s", "status": "labelled", "total": "2",
             "car": "", "motorcycle": "", "bus": "", "truck": "", "bicycle": ""},
            {"camera_id": "c", "clip": "b", "approach_id": "s", "status": "unusable", "total": ""},
        ]
        labels, unusable = load_ground_truth(rows)
        self.assertEqual(labels[("c", "a", "s")].total, 2)
        self.assertIsNone(labels[("c", "a", "s")].split)
        self.assertEqual(unusable, {("c", "b")})


def pair(cam: str, gt: int, pred: int, period: str = "day", model: str = "m", conf: float = 0.25) -> Pair:
    return Pair(model, conf, "J1", cam, f"clip{gt}{pred}", period, "southbound_in", gt, pred, 10.0)


class MetricTests(unittest.TestCase):
    def test_summary(self) -> None:
        s = Summary.of([pair("a", 10, 9), pair("a", 0, 0), pair("a", 5, 8)])
        self.assertEqual((s.gt_sum, s.pred_sum), (15, 17))
        self.assertAlmostEqual(s.rel_error, 2 / 15)
        self.assertAlmostEqual(s.mae, 4 / 3)
        self.assertAlmostEqual(s.exact, 1 / 3)
        self.assertAlmostEqual(s.within1, 2 / 3)
        self.assertIsNone(Summary.of([pair("a", 0, 1)]).rel_error)

    def test_verdict_and_recommendation(self) -> None:
        good = [pair("a", 10, 10), pair("b", 10, 11)]
        bad_camera = [pair("a", 10, 10), pair("b", 10, 13)]
        self.assertTrue(config_verdict(good, Targets())["meets_targets"])
        verdict = config_verdict(bad_camera, Targets())
        self.assertFalse(verdict["meets_targets"])
        self.assertTrue(any("b" in f for f in verdict["fails"]))
        verdicts = {("m", 0.25): config_verdict(bad_camera), ("n", 0.4): config_verdict(good)}
        self.assertEqual(choose_recommendation(verdicts), ("n", 0.4))

    def test_report_renders(self) -> None:
        pairs = [pair("a", 3, 2, "day"), pair("a", 1, 1, "night"), pair("a", 3, 3, "day", conf=0.4)]
        text = render_report(pairs, targets=Targets(), periods=PeriodConfig(), notes=["n1"], generated_utc="now")
        self.assertIn("Recommended", text)
        self.assertIn("| night |", text)
        self.assertIn("Worst clips", text)


if __name__ == "__main__":
    unittest.main()
