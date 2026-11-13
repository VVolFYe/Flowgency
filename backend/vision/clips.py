"""Clip discovery, timestamp parsing, and frame access.

Clip files are ``<clips_dir>/<camera_id>/<YYYYMMDD_HHMMSS>.mp4``; the filename is
the *download* time in Europe/Bucharest local time (written by
``jamcam_fetch.py`` with ``datetime.now()``). It is converted to UTC exactly once,
here, and everything downstream uses UTC only.

Approximation: TfL publishes a clip a few minutes before it is downloaded, so
the true capture window ends at or slightly before the download time. Spot
checks of the timestamp burned into the video showed a 0-5 minute lag.

DST: a local time in the repeated autumn hour is ambiguous; the earlier
instant (``fold=0``, summer offset) is used. A local time inside the spring gap
cannot be produced by a real clock and is rejected.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:  # pragma: no cover
    import numpy as np

FILENAME_TZ = ZoneInfo("Europe/Bucharest")
CLIP_STEM_RE = re.compile(r"^\d{8}_\d{6}$")
CLIP_STEM_FORMAT = "%Y%m%d_%H%M%S"


def parse_clip_time_utc(stem: str, tz: ZoneInfo = FILENAME_TZ) -> datetime:
    """Convert a ``YYYYMMDD_HHMMSS`` local-download-time stem to an aware UTC datetime."""
    if not CLIP_STEM_RE.fullmatch(stem):
        raise ValueError(f"clip name {stem!r} is not YYYYMMDD_HHMMSS")
    naive = datetime.strptime(stem, CLIP_STEM_FORMAT)
    local = naive.replace(tzinfo=tz, fold=0)
    utc = local.astimezone(UTC)
    if utc.astimezone(tz).replace(tzinfo=None) != naive:
        raise ValueError(f"clip time {stem!r} does not exist in {tz.key} (DST gap)")
    return utc


def format_utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Clip:
    camera_id: str
    path: Path
    observed_at_utc: datetime  # download time converted to UTC = window end (approx.)

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def key(self) -> str:
        """Stable identifier used in logs and eval sets: ``<camera_id>/<stem>``."""
        return f"{self.camera_id}/{self.path.stem}"

    @classmethod
    def from_path(cls, path: Path, camera_id: str | None = None) -> Clip:
        return cls(camera_id or path.parent.name, path, parse_clip_time_utc(path.stem))


def discover_clips(clips_dir: Path, camera_id: str) -> list[Clip]:
    """All parseable clips for one camera, oldest first."""
    folder = clips_dir / camera_id
    if not folder.is_dir():
        return []
    clips = [
        Clip.from_path(p, camera_id)
        for p in folder.glob("*.mp4")
        if CLIP_STEM_RE.fullmatch(p.stem)
    ]
    return sorted(clips, key=lambda c: (c.observed_at_utc, c.name))


def find_clip(clips_dir: Path, key: str) -> Clip:
    camera_id, _, stem = key.partition("/")
    path = clips_dir / camera_id / f"{stem}.mp4"
    if not path.exists():
        raise FileNotFoundError(path)
    return Clip.from_path(path, camera_id)


# --- video access (OpenCV imported lazily so pure code needs no CV stack) ---


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    frame_count: int

    @property
    def duration_s(self) -> float:
        return self.frame_count / self.fps if self.fps > 0 else 0.0


def _cv2() -> Any:
    import cv2

    return cv2


def probe(path: Path) -> VideoInfo:
    cv2 = _cv2()
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise OSError(f"cannot open video {path}")
        return VideoInfo(
            width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fps=float(cap.get(cv2.CAP_PROP_FPS)),
            frame_count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        )
    finally:
        cap.release()


def read_frames(path: Path) -> list[np.ndarray]:
    """Decode every frame (clips are ~10 s at 352x288, so this is small)."""
    cv2 = _cv2()
    cap = cv2.VideoCapture(str(path))
    frames = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
    finally:
        cap.release()
    return frames


def iter_frames(path: Path) -> Iterator[np.ndarray]:
    cv2 = _cv2()
    cap = cv2.VideoCapture(str(path))
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                return
            yield frame
    finally:
        cap.release()
