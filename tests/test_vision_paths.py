"""Data folder resolution, missing-input messages, and the repository write guard (pure, no media)."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from backend.vision.paths import REPO_DATA_DIR, REPO_ROOT, SAMPLES_DIR, VisionPaths, missing_data_message
from backend.vision.pipeline import ensure_outside_repo


class DataFolderTests(unittest.TestCase):
    def test_default_is_the_gitignored_repo_data_folder(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("UNIHACK_DIR", None)
            self.assertEqual(VisionPaths.from_env().unihack_dir, REPO_ROOT / "data")
        self.assertEqual(REPO_DATA_DIR, REPO_ROOT / "data")

    def test_unihack_dir_overrides_the_default(self) -> None:
        with mock.patch.dict(os.environ, {"UNIHACK_DIR": "/srv/flowgency-data"}):
            paths = VisionPaths.from_env()
        self.assertEqual(paths.unihack_dir, Path("/srv/flowgency-data"))
        self.assertEqual(paths.resolve("youtube/clip.mp4"), Path("/srv/flowgency-data/youtube/clip.mp4"))

    def test_missing_message_says_what_to_do(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("UNIHACK_DIR", None)
            text = missing_data_message("video", REPO_DATA_DIR / "youtube" / "clip.mp4")
        self.assertIn("video not found", text)
        self.assertIn("UNIHACK_DIR is not set", text)
        self.assertIn("Set UNIHACK_DIR", text)
        self.assertIn("data/", text)
        with mock.patch.dict(os.environ, {"UNIHACK_DIR": "/srv/x"}):
            self.assertIn("UNIHACK_DIR=/srv/x", VisionPaths.from_env().missing("weights", Path("/srv/x/weights/a.pt")))

    def test_repo_guard_allows_only_the_data_folder(self) -> None:
        self.assertEqual(ensure_outside_repo(REPO_DATA_DIR / "vision_output" / "x.json"),
                         (REPO_DATA_DIR / "vision_output" / "x.json").resolve())
        for tracked in (REPO_ROOT / "out.mp4", REPO_ROOT / "backend" / "vision" / "samples" / "x.jsonl"):
            with self.assertRaises(ValueError):
                ensure_outside_repo(tracked)

    def test_committed_samples_need_no_data_folder(self) -> None:
        with mock.patch.dict(os.environ, {"UNIHACK_DIR": "/nonexistent/data"}):
            for sample in ("youtube_30s",):
                for name in ("events.jsonl", "counts.jsonl"):
                    lines = (SAMPLES_DIR / sample / name).read_text(encoding="utf-8").splitlines()
                    self.assertTrue(lines)
                    json.loads(lines[0])


if __name__ == "__main__":
    unittest.main()
