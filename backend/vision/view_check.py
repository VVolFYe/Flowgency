"""Decide whether each clip is usable and still shows the configured camera view.

Per-clip scan (cheap, CPU, no model), in order:

1. ``placeholder``: TfL "Camera ... in use keeping London moving" /
   "unobtainable" cards: near-uniform, unsaturated grey frames with text.
2. ``too_short``: under ``min_duration_s`` seconds of decodable video.
3. ``corrupt``: decoder garbage. JamCam clips often start with 1-2 s of
   vertically streaked frames (the stream starts before a keyframe), sometimes
   only in the lower part of the image. A frame is corrupt when any of six
   horizontal scene bands has vertical/horizontal gradient energy below 0.35
   (streaked bands measure < 0.2; across 48k later frames the minimum was
   0.54). The leading corrupt run is trimmed and the analysed window starts
   after it; the clip is skipped when later corrupt frames exceed 10 % or less
   than ``min_duration_s`` of clean video remains.

View check (per camera, over all clips):

Each clip is summarised by the temporal median of 9 clean frames (removes
moving vehicles). ORB features on CLAHE-normalised greyscale, with the burned-in
TfL overlays masked out, are matched (ratio test) and a RANSAC homography is
fitted. Two images show the *same view* when the fit has at least
``min_inliers`` inliers whose median pixel displacement is at most
``max_displacement_px`` (static scenery stays put; pan/tilt/zoom moves it).

Day-vs-night and moving-shadow lighting changes often leave too few confident
matches against a single reference frame, so links are also formed between each
clip and its ``chain_neighbours`` nearest clips in time (minutes apart, similar
lighting). A clip is accepted when a chain of same-view links connects it to the
reference frame. A real view change breaks every link into the changed period,
so those clips are rejected as ``view_changed`` (a confident match to the
reference with large displacement) or ``view_unverified`` (no confident link).

Calibration (2026-11-13, 797 clips, J1-J5, reference = one frame of the latest
daytime clip): confident same-view matches had median inlier displacement
<= 2.3 px (p95 per camera 1.0-2.3 px), so the limit is 3 px with >= 20 inliers.
Direct reference matches covered 35-85 % of clips per camera (night and
moving-shadow clips fall short); chaining accepted all non-defective clips,
consistent with visual inspection showing no real view change in this data.
Synthetic changes applied to real clip medians (pan 4/6/12 px, tilt 8 px, zoom
x1.10) were rejected on every camera both for a single clip and a 12-clip block.
Known gaps: a 3 degree roll about the image centre on J5 was not rejected
(PTZ cameras do not roll); a rejected block can cut the chain and make clips
beyond it ``view_unverified`` (fails safe: skipped, not miscounted).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

# Burned-in overlay regions (timestamp + camera number, TfL logo, location
# caption), as (x1, y1, x2, y2) fractions of the 352x288 frame.
OVERLAY_BOXES = (
    (0.0, 0.0, 0.38, 0.21),
    (0.72, 0.0, 1.0, 0.18),
    (0.0, 0.93, 1.0, 1.0),
)
SCAN_VERSION = 2


@dataclass(frozen=True)
class ViewCheckConfig:
    min_duration_s: float = 3.0
    placeholder_uniform_fraction: float = 0.80  # share of scene pixels within +-10 grey levels of the median
    placeholder_max_saturation: float = 20.0
    corrupt_gradient_ratio: float = 0.35  # per-band mean|d/dy| / mean|d/dx| below this -> streaked
    corrupt_bands: int = 6
    max_corrupt_fraction: float = 0.10
    median_frames: int = 9
    orb_features: int = 1500
    min_inliers: int = 20
    max_displacement_px: float = 3.0
    chain_neighbours: int = 3


# --- per-frame flags ---------------------------------------------------------------


def overlay_mask(shape: tuple[int, int]) -> np.ndarray:
    """uint8 mask (255 = scene) excluding burned-in overlays."""
    height, width = shape
    mask = np.full((height, width), 255, np.uint8)
    for x1, y1, x2, y2 in OVERLAY_BOXES:
        mask[int(y1 * height) : int(np.ceil(y2 * height)), int(x1 * width) : int(np.ceil(x2 * width))] = 0
    return mask


@dataclass(frozen=True)
class FrameFlags:
    placeholder: bool
    corrupt: bool


def frame_flags(frame: np.ndarray, cfg: ViewCheckConfig = ViewCheckConfig()) -> FrameFlags:
    height = frame.shape[0]
    scene = frame[int(0.21 * height) : int(0.93 * height)]
    gray = cv2.cvtColor(scene, cv2.COLOR_BGR2GRAY).astype(np.float32)
    median = float(np.median(gray))
    uniform = float(np.mean(np.abs(gray - median) <= 10.0))
    saturation = float(cv2.cvtColor(scene, cv2.COLOR_BGR2HSV)[..., 1].mean())
    placeholder = uniform >= cfg.placeholder_uniform_fraction and saturation <= cfg.placeholder_max_saturation
    corrupt = False
    if not placeholder:
        for band in np.array_split(gray, cfg.corrupt_bands, axis=0):
            dy = float(np.abs(np.diff(band, axis=0)).mean())
            dx = float(np.abs(np.diff(band, axis=1)).mean())
            if dx > 2.0 and dy / dx < cfg.corrupt_gradient_ratio:
                corrupt = True
                break
    return FrameFlags(placeholder, corrupt)


def median_frame(frames: Sequence[np.ndarray], count: int) -> np.ndarray:
    """Temporal median of evenly spaced frames: suppresses moving vehicles."""
    if len(frames) <= count:
        picks = list(frames)
    else:
        picks = [frames[i] for i in np.linspace(0, len(frames) - 1, count).round().astype(int)]
    return np.median(np.stack(picks), axis=0).astype(np.uint8)


# --- per-clip scan -----------------------------------------------------------------


@dataclass(frozen=True)
class ClipScan:
    frame_count: int
    fps: float
    reason: str | None  # too_short | placeholder | corrupt | None
    start_frame: int  # first analysed frame (leading corrupt run trimmed)
    corrupt_frames: tuple[int, ...]  # never fed to the tracker
    detail: str = ""

    @property
    def analysed_duration_s(self) -> float:
        return (self.frame_count - self.start_frame) / self.fps if self.fps > 0 else 0.0


def scan_frames(
    frames: Sequence[np.ndarray], fps: float, cfg: ViewCheckConfig = ViewCheckConfig()
) -> tuple[ClipScan, np.ndarray | None]:
    """Usability flags plus the clean median frame (``None`` when unusable)."""
    n = len(frames)
    duration = n / fps if fps > 0 else 0.0
    flags = [frame_flags(f, cfg) for f in frames]
    placeholder = sum(f.placeholder for f in flags)
    if placeholder:
        return ClipScan(n, fps, "placeholder", 0, (), f"{placeholder}/{n} placeholder frames"), None
    if not n or duration < cfg.min_duration_s:
        return ClipScan(n, fps, "too_short", 0, (), f"{n} frames, {duration:.2f}s"), None
    corrupt = tuple(i for i, f in enumerate(flags) if f.corrupt)
    start = 0
    while start < n and flags[start].corrupt:
        start += 1
    later = [i for i in corrupt if i >= start]
    clean_s = (n - start - len(later)) / fps
    if len(later) > cfg.max_corrupt_fraction * (n - start) or clean_s < cfg.min_duration_s:
        detail = f"{len(corrupt)}/{n} corrupt frames, {clean_s:.2f}s clean"
        return ClipScan(n, fps, "corrupt", start, corrupt, detail), None
    bad = set(corrupt)
    median = median_frame([f for i, f in enumerate(frames) if i not in bad], cfg.median_frames)
    detail = f"trimmed {start} leading corrupt frames" if start else ""
    return ClipScan(n, fps, None, start, corrupt, detail), median


# --- view matching -----------------------------------------------------------------


@dataclass(frozen=True)
class Features:
    keypoints: np.ndarray  # (N, 2) float32
    descriptors: np.ndarray | None


def features(image: np.ndarray, cfg: ViewCheckConfig = ViewCheckConfig()) -> Features:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4)).apply(gray)
    mask = cv2.erode(overlay_mask(gray.shape), np.ones((7, 7), np.uint8))
    orb = cv2.ORB_create(cfg.orb_features, fastThreshold=10)
    kps, desc = orb.detectAndCompute(gray, mask)
    return Features(np.float32([k.pt for k in kps]).reshape(-1, 2), desc)


@dataclass(frozen=True)
class ViewMatch:
    inliers: int
    displacement_px: float | None  # median displacement of RANSAC inliers

    def same(self, cfg: ViewCheckConfig) -> bool:
        return (
            self.inliers >= cfg.min_inliers
            and self.displacement_px is not None
            and self.displacement_px <= cfg.max_displacement_px
        )

    def different(self, cfg: ViewCheckConfig) -> bool:
        return (
            self.inliers >= cfg.min_inliers
            and self.displacement_px is not None
            and self.displacement_px > cfg.max_displacement_px
        )


def match_views(a: Features, b: Features) -> ViewMatch:
    if a.descriptors is None or b.descriptors is None or len(a.keypoints) < 8 or len(b.keypoints) < 8:
        return ViewMatch(0, None)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    good = [
        pair[0]
        for pair in matcher.knnMatch(a.descriptors, b.descriptors, k=2)
        if len(pair) == 2 and pair[0].distance < 0.8 * pair[1].distance
    ]
    if len(good) < 8:
        return ViewMatch(0, None)
    src = a.keypoints[[m.queryIdx for m in good]]
    dst = b.keypoints[[m.trainIdx for m in good]]
    homography, inlier_mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if homography is None or inlier_mask is None:
        return ViewMatch(0, None)
    keep = inlier_mask.ravel().astype(bool)
    displacement = float(np.median(np.linalg.norm(dst[keep] - src[keep], axis=1))) if keep.any() else None
    return ViewMatch(int(keep.sum()), displacement)


# --- per-camera view index -----------------------------------------------------------


@dataclass
class ViewDecision:
    usable: bool
    reason: str | None  # too_short | placeholder | corrupt | no_reference | view_changed | view_unverified
    evidence: str
    reference_match: ViewMatch | None = None
    scan: ClipScan | None = None


@dataclass
class ViewIndex:
    decisions: dict[str, ViewDecision] = field(default_factory=dict)

    def __getitem__(self, key: str) -> ViewDecision:
        return self.decisions[key]


def decide_views(
    keys: Sequence[str],
    scans: dict[str, ClipScan],
    clip_features: dict[str, Features],
    reference: Features | None,
    cfg: ViewCheckConfig = ViewCheckConfig(),
) -> ViewIndex:
    """Chain same-view links from the reference through time-adjacent clips.

    ``keys`` must be in time order; ``clip_features`` holds the clips whose scan
    found no defect.
    """
    index = ViewIndex()
    candidates = [k for k in keys if scans[k].reason is None]
    for key in keys:
        if scans[key].reason is not None:
            index.decisions[key] = ViewDecision(False, scans[key].reason, scans[key].detail, None, scans[key])
    if reference is None:
        for key in candidates:
            index.decisions[key] = ViewDecision(False, "no_reference", "camera has no reference frame", None, scans[key])
        return index

    direct = {k: match_views(reference, clip_features[k]) for k in candidates}
    accepted: dict[str, str] = {
        k: f"reference match: {m.inliers} inliers, {m.displacement_px:.1f}px"
        for k, m in direct.items()
        if m.same(cfg)
    }
    neighbours: dict[str, list[str]] = {k: [] for k in candidates}
    for i, key in enumerate(candidates):
        for other in candidates[i + 1 : i + 1 + cfg.chain_neighbours]:
            if match_views(clip_features[key], clip_features[other]).same(cfg):
                neighbours[key].append(other)
                neighbours[other].append(key)
    frontier = sorted(accepted)
    while frontier:
        key = frontier.pop()
        for other in neighbours[key]:
            if other not in accepted:
                accepted[other] = f"chained via {key.rsplit('/', 1)[-1]}"
                frontier.append(other)

    for key in candidates:
        match = direct[key]
        if key in accepted:
            index.decisions[key] = ViewDecision(True, None, accepted[key], match, scans[key])
        elif match.different(cfg):
            index.decisions[key] = ViewDecision(
                False, "view_changed",
                f"reference match {match.inliers} inliers but {match.displacement_px:.1f}px displacement",
                match, scans[key],
            )
        else:
            index.decisions[key] = ViewDecision(
                False, "view_unverified", "no confident same-view link to the reference", match, scans[key]
            )
    return index


class ScanCache:
    """Per-clip scan results and median frames, cached under UNIHACK_DIR."""

    def __init__(self, root: Path, camera_id: str, cfg: ViewCheckConfig) -> None:
        self.dir = root / camera_id
        self.cfg = cfg
        self.meta_path = self.dir / "scans.json"
        self.meta: dict[str, Any] = {}
        self._fingerprint = json.dumps({"v": SCAN_VERSION, **asdict(cfg)}, sort_keys=True)
        if self.meta_path.exists():
            data = json.loads(self.meta_path.read_text(encoding="utf-8"))
            if data.get("fingerprint") == self._fingerprint:
                self.meta = data.get("clips", {})

    def get(self, stem: str, size: int) -> tuple[ClipScan, np.ndarray | None] | None:
        entry = self.meta.get(stem)
        if not entry or entry.get("size") != size:
            return None
        scan = ClipScan(**{**entry["scan"], "corrupt_frames": tuple(entry["scan"]["corrupt_frames"])})
        median = None
        if scan.reason is None:
            median = cv2.imread(str(self.dir / f"{stem}.png"))
            if median is None:
                return None
        return scan, median

    def put(self, stem: str, size: int, scan: ClipScan, median: np.ndarray | None) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        if median is not None:
            cv2.imwrite(str(self.dir / f"{stem}.png"), median)
        self.meta[stem] = {"size": size, "scan": asdict(scan)}

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        payload = {"fingerprint": self._fingerprint, "clips": self.meta}
        tmp = self.meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self.meta_path)


def build_view_index(
    clips: Sequence[Any],
    reference_image: np.ndarray | None,
    cache: ScanCache,
    load_frames: Callable[[Path], list[np.ndarray]],
    probe_fps: Callable[[Path], float],
    cfg: ViewCheckConfig = ViewCheckConfig(),
    progress: Callable[[str], None] | None = None,
) -> ViewIndex:
    """Scan (or load cached scans of) all clips of one camera and decide views."""
    scans: dict[str, ClipScan] = {}
    feats: dict[str, Features] = {}
    for n, clip in enumerate(clips, 1):
        size = clip.path.stat().st_size
        cached = cache.get(clip.name, size)
        if cached is None:
            scan, median = scan_frames(load_frames(clip.path), probe_fps(clip.path), cfg)
            cache.put(clip.name, size, scan, median)
            if progress and n % 25 == 0:
                progress(f"scanned {n}/{len(clips)} clips")
        else:
            scan, median = cached
        scans[clip.key] = scan
        if median is not None:
            feats[clip.key] = features(median, cfg)
    cache.save()
    reference = features(reference_image, cfg) if reference_image is not None else None
    return decide_views([c.key for c in clips], scans, feats, reference, cfg)
