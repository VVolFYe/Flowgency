"""Clip filename timestamps: Europe/Bucharest download time -> UTC."""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from backend.vision.clips import Clip, discover_clips, duration_matches, format_utc, parse_clip_time_utc


class DurationMatchTests(unittest.TestCase):
    def test_last_frame_must_fall_in_the_last_output_second(self) -> None:
        self.assertTrue(duration_matches(6329, 23.976, 263.0))   # the youtube clip: 263.97 s, t_s 0-263
        self.assertFalse(duration_matches(6392, 23.976, 263.0))  # its container header count (266.6 s)
        self.assertFalse(duration_matches(720, 23.976, 263.0))   # a 30 s cut
        self.assertTrue(duration_matches(10, 10.0, 0.0))         # frames 0-9 all in second 0
        self.assertFalse(duration_matches(11, 10.0, 0.0))
        self.assertFalse(duration_matches(0, 25.0, 0.0))


class ClipTimestampTests(unittest.TestCase):
    def test_winter_offset_is_plus_two(self) -> None:
        self.assertEqual(
            parse_clip_time_utc("20261113_173908"), datetime(2026, 11, 13, 15, 39, 8, tzinfo=UTC)
        )

    def test_summer_offset_is_plus_three(self) -> None:
        self.assertEqual(
            parse_clip_time_utc("20260715_120000"), datetime(2026, 7, 15, 9, 0, 0, tzinfo=UTC)
        )

    def test_autumn_dst_change_2026_10_25(self) -> None:
        # Clocks go back 04:00 EEST -> 03:00 EET on 25 Oct 2026.
        self.assertEqual(
            parse_clip_time_utc("20261025_022959"), datetime(2026, 10, 24, 23, 29, 59, tzinfo=UTC)
        )
        # Repeated hour: earliest instant (summer offset) is chosen.
        self.assertEqual(
            parse_clip_time_utc("20261025_033000"), datetime(2026, 10, 25, 0, 30, 0, tzinfo=UTC)
        )
        self.assertEqual(
            parse_clip_time_utc("20261025_040000"), datetime(2026, 10, 25, 2, 0, 0, tzinfo=UTC)
        )

    def test_spring_dst_change_2026_03_29(self) -> None:
        # Clocks go forward 03:00 EET -> 04:00 EEST on 29 Mar 2026.
        self.assertEqual(
            parse_clip_time_utc("20260329_025959"), datetime(2026, 3, 29, 0, 59, 59, tzinfo=UTC)
        )
        self.assertEqual(
            parse_clip_time_utc("20260329_040000"), datetime(2026, 3, 29, 1, 0, 0, tzinfo=UTC)
        )
        with self.assertRaises(ValueError):
            parse_clip_time_utc("20260329_033000")  # does not exist locally

    def test_bad_names_rejected(self) -> None:
        for stem in ("2026-11-13_173908", "20261113", "20261313_000000", "x"):
            with self.subTest(stem=stem), self.assertRaises(ValueError):
                parse_clip_time_utc(stem)

    def test_format_utc(self) -> None:
        self.assertEqual(format_utc(parse_clip_time_utc("20261113_000501")), "2026-11-12T22:05:01Z")

    def test_discover_sorted_and_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cam = Path(tmp) / "JamCams_X"
            cam.mkdir()
            for name in ("20261113_101500.mp4", "20261112_235900.mp4", "notes.mp4", "a.txt"):
                (cam / name).write_bytes(b"")
            clips = discover_clips(Path(tmp), "JamCams_X")
            self.assertEqual([c.name for c in clips], ["20261112_235900", "20261113_101500"])
            self.assertEqual(clips[0].key, "JamCams_X/20261112_235900")
            self.assertEqual(clips[0].observed_at_utc.tzinfo, UTC)
            self.assertEqual(discover_clips(Path(tmp), "missing"), [])
            self.assertIsInstance(clips[0], Clip)


if __name__ == "__main__":
    unittest.main()
