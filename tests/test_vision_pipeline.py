"""View check and replay pipeline on synthetic media (needs OpenCV; no model, no clips).

Run with the vision environment, e.g.
``~/.venvs/flowgency-vision/bin/python -m unittest tests.test_vision_pipeline``.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HAS_CV = importlib.util.find_spec("cv2") is not None and importlib.util.find_spec("numpy") is not None

if HAS_CV:
    import cv2
    import numpy as np

    from backend.models.observation import TrafficObservation
    from backend.vision.clips import Clip
    from backend.vision.config import ApproachConfig, CameraConfig
    from backend.vision.counting import TrackedBox
    from backend.vision.paths import REPO_ROOT
    from backend.vision.pipeline import (
        append_run_log, ensure_outside_repo, process_clip, run_log_row, select_evenly, write_observations,
    )
    from backend.vision.view_check import (
        ViewCheckConfig, decide_views, features, frame_flags, match_views, scan_frames,
    )

W, H = 352, 288


def scene(seed: int = 0) -> np.ndarray:
    """Textured synthetic street-like scene (deterministic)."""
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), 90, np.uint8)
    for _ in range(140):
        x, y = int(rng.integers(0, W)), int(rng.integers(0, H))
        colour = tuple(int(c) for c in rng.integers(0, 255, 3))
        if rng.random() < 0.5:
            cv2.rectangle(img, (x, y), (x + int(rng.integers(5, 40)), y + int(rng.integers(5, 40))), colour, -1)
        else:
            cv2.line(img, (x, y), (int(rng.integers(0, W)), int(rng.integers(0, H))), colour, 2)
    return img


def shifted(img: np.ndarray, dx: int, dy: int = 0) -> np.ndarray:
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (W, H), borderMode=cv2.BORDER_REFLECT)


def streaked(img: np.ndarray) -> np.ndarray:
    out = img.copy()
    out[150:] = out[150:151]  # lower part: every row identical -> vertical streaks
    return out


def placeholder() -> np.ndarray:
    img = np.full((H, W, 3), 128, np.uint8)
    cv2.putText(img, "Camera in use keeping", (20, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return img


@unittest.skipUnless(HAS_CV, "OpenCV/numpy not installed (vision environment only)")
class FrameFlagTests(unittest.TestCase):
    def test_flags(self) -> None:
        self.assertEqual(frame_flags(scene()).placeholder, False)
        self.assertEqual(frame_flags(scene()).corrupt, False)
        self.assertTrue(frame_flags(placeholder()).placeholder)
        self.assertTrue(frame_flags(streaked(scene())).corrupt)

    def test_scan_trims_leading_corrupt_run(self) -> None:
        frames = [streaked(scene())] * 20 + [scene()] * 230
        scan, median = scan_frames(frames, 25.0)
        self.assertIsNone(scan.reason)
        self.assertEqual(scan.start_frame, 20)
        self.assertEqual(len(scan.corrupt_frames), 20)
        self.assertAlmostEqual(scan.analysed_duration_s, 230 / 25)
        self.assertIsNotNone(median)

    def test_scan_rejects_placeholder_short_and_scattered_corruption(self) -> None:
        self.assertEqual(scan_frames([placeholder()] * 25, 25.0)[0].reason, "placeholder")
        self.assertEqual(scan_frames([scene()] * 50, 25.0)[0].reason, "too_short")
        frames = [scene()] * 100 + [streaked(scene())] * 40 + [scene()] * 110
        self.assertEqual(scan_frames(frames, 25.0)[0].reason, "corrupt")


@unittest.skipUnless(HAS_CV, "OpenCV/numpy not installed (vision environment only)")
class ViewMatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = ViewCheckConfig()

    def test_same_view_survives_lighting_change(self) -> None:
        ref = scene()
        darker = cv2.convertScaleAbs(ref, alpha=0.6, beta=-10)
        self.assertTrue(match_views(features(ref), features(darker)).same(self.cfg))

    def test_pan_is_different(self) -> None:
        ref = scene()
        match = match_views(features(ref), features(shifted(ref, 12, 5)))
        self.assertTrue(match.different(self.cfg), match)

    def test_chain_accepts_neighbours_and_rejects_moved_block(self) -> None:
        base = scene()
        images = {}
        keys = [f"cam/2026111{3}_{i:06d}" for i in range(8)]
        for i, key in enumerate(keys):
            img = cv2.convertScaleAbs(base, alpha=1.0 - 0.08 * i, beta=0)  # gradual lighting drift
            images[key] = shifted(img, 15) if i in (5, 6) else img
        scans = {k: scan_frames([images[k]] * 100, 25.0)[0] for k in keys}
        feats = {k: features(images[k]) for k in keys}
        index = decide_views(keys, scans, feats, features(base), self.cfg)
        self.assertEqual([index[k].usable for k in keys], [True] * 5 + [False, False, True])
        self.assertIn(index[keys[5]].reason, ("view_changed", "view_unverified"))

    def test_no_reference_skips_everything(self) -> None:
        keys = ["cam/a"]
        scans = {"cam/a": scan_frames([scene()] * 100, 25.0)[0]}
        index = decide_views(keys, scans, {"cam/a": features(scene())}, None, self.cfg)
        self.assertEqual(index["cam/a"].reason, "no_reference")


class FakeTracker:
    """Moves one car down through the southbound line; resets between clips."""

    model_id = "fake+bytetrack"
    conf = 0.25

    def __init__(self) -> None:
        self.frame = 0
        self.resets = 0

    def begin_clip(self, clip_key=None, size=0) -> None:
        self.frame = 0
        self.resets += 1

    def end_clip(self) -> None:
        pass

    def track(self, frame, frame_index=None) -> list:
        y = 60 + 2 * self.frame
        self.frame += 1
        return [TrackedBox(1, "car", 0.9, (90, y - 20, 110, y))]


@unittest.skipUnless(HAS_CV, "OpenCV/numpy not installed (vision environment only)")
class PipelineTests(unittest.TestCase):
    camera = None

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # Temporary test config (not cameras.json): one approach, line y=100.
        self.camera = CameraConfig(
            intersection_id="J9", camera_id="cam", frame_size=(W, H),
            approaches=(ApproachConfig(approach_id="southbound_in", line=((50, 100), (150, 100)),
                                       inbound_point=(100, 130)),),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_clip(self, frames: list) -> Clip:
        path = self.dir / "cam" / "20261113_173908.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25.0, (W, H))
        for frame in frames:
            writer.write(frame)
        writer.release()
        return Clip.from_path(path)

    def test_process_clip_emits_valid_observation(self) -> None:
        frames = [scene()] * 120
        clip = self.write_clip(frames)
        from backend.vision.clips import read_frames

        scan, median = scan_frames(read_frames(clip.path), 25.0)
        index = decide_views([clip.key], {clip.key: scan}, {clip.key: features(median)}, features(scene()))
        tracker = FakeTracker()
        result = process_clip(clip, index[clip.key], self.camera, tracker)
        self.assertEqual(result.status, "ok", result.detail)
        self.assertEqual(tracker.resets, 1)
        obs = result.observation
        TrafficObservation.model_validate(obs)
        self.assertEqual(obs["observed_at"], "2026-11-13T15:39:08Z")
        self.assertAlmostEqual(obs["window_duration_s"], 120 / 25)
        self.assertEqual(obs["vehicle_counts_by_approach"]["southbound_in"]["car"], 1)
        self.assertAlmostEqual(obs["confidence"], 0.9)
        self.assertNotIn("emergency_detections", obs)

        row = run_log_row(result, self.camera, "run-x", "2026-11-13T00:00:00Z", "fake", 0.25)
        log = self.dir / "out" / "run_log.csv"
        append_run_log(log, [row])
        append_run_log(log, [row])
        self.assertEqual(len(log.read_text().splitlines()), 3)
        jsonl = self.dir / "out" / "J9.jsonl"
        write_observations(jsonl, [obs])
        self.assertEqual(json.loads(jsonl.read_text().splitlines()[0])["camera_id"], "cam")

    def test_skipped_clip_produces_no_observation(self) -> None:
        clip = self.write_clip([placeholder()] * 30)
        from backend.vision.clips import read_frames

        scan, _ = scan_frames(read_frames(clip.path), 25.0)
        index = decide_views([clip.key], {clip.key: scan}, {}, features(scene()))
        result = process_clip(clip, index[clip.key], self.camera, FakeTracker())
        self.assertEqual((result.status, result.reason, result.observation), ("skipped", "placeholder", None))

    def test_select_evenly_and_repo_guard(self) -> None:
        self.assertEqual(select_evenly(list(range(10)), 3), [0, 4, 9])  # linspace 4.5 rounds half-to-even
        self.assertEqual(select_evenly([1, 2], None), [1, 2])
        self.assertEqual(select_evenly([1, 2], 0), [])
        with self.assertRaises(ValueError):
            ensure_outside_repo(REPO_ROOT / "out.mp4")
        self.assertEqual(ensure_outside_repo(self.dir / "x"), (self.dir / "x").resolve())


if __name__ == "__main__":
    unittest.main()
