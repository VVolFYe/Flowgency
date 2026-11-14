"""Duplicate-track filter applied to ByteTrack output (pure; no CV dependencies).

Root cause of the London double counts (tracker side)
-----------------------------------------------------
When the detector flips a vehicle from a large ``truck`` box to a smaller
``car`` box, ByteTrack's score-fused cost (``1 - IoU * score``) can exceed its
match threshold, so the smaller box starts a *new* track. When the large box
returns, ByteTrack re-activates the original (lost) track. Both IDs cross the
counting line: traced in J3 clip ``20261113_174113`` (tracks 25 then 22, six
frames apart) and J4 clip ``20261113_173909`` (tracks 7 and 13).

This filter maps such a newborn track ID onto the existing track it
duplicates, so downstream counters see one ID per vehicle:

* **nested**: when the new ID first appears, an older track is visible in the
  same frame and at least ``contain`` of the smaller box lies inside the other;
* **reborn**: an older track was last seen at most ``max_gap`` frames ago (and
  is not visible now), and at least ``reborn_overlap`` of the smaller box
  overlaps its last observed box.

If two raw tracks map to the same ID in one frame, the original track's box is
kept (else the higher-confidence one). Aliases are permanent for the clip.
The gap is short (6 frames, ~0.25 s) so a different vehicle arriving where a
lost one stood is unlikely to be merged with it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Protocol, TypeVar

Box = tuple[float, float, float, float]


class HasTrack(Protocol):
    track_id: int
    confidence: float
    bbox: Box


T = TypeVar("T", bound=HasTrack)


def ios(a: Box, b: Box) -> float:
    """Intersection over the smaller box area."""
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return iw * ih / smaller if smaller > 0 else 0.0


@dataclass
class _Last:
    frame: int
    bbox: Box


class DuplicateTrackFilter:
    """Feed each frame's tracked boxes in frame order; returns them with canonical IDs."""

    def __init__(self, contain: float = 0.85, reborn_overlap: float = 0.7, max_gap: int = 6) -> None:
        self.contain = contain
        self.reborn_overlap = reborn_overlap
        self.max_gap = max_gap
        self.aliases: dict[int, int] = {}  # raw track ID -> canonical ID (only for merged IDs)
        self._seen: set[int] = set()
        self._last: dict[int, _Last] = {}  # canonical ID -> last observation

    def canonical(self, raw_id: int) -> int:
        return self.aliases.get(raw_id, raw_id)

    def update(self, frame_index: int, boxes: Iterable[T]) -> list[T]:
        boxes = list(boxes)
        known = [b for b in boxes if b.track_id in self._seen]
        newborn = sorted((b for b in boxes if b.track_id not in self._seen), key=lambda b: b.track_id)
        visible = {self.canonical(b.track_id): b.bbox for b in known}
        for box in newborn:
            self._seen.add(box.track_id)
            target = self._match(frame_index, box.bbox, visible)
            if target is not None:
                self.aliases[box.track_id] = target
            else:
                visible.setdefault(box.track_id, box.bbox)
        chosen: dict[int, T] = {}
        for box in boxes:
            cid = self.canonical(box.track_id)
            current = chosen.get(cid)
            if current is None or self._prefer(box, current, cid):
                chosen[cid] = box
        out = []
        for cid, box in chosen.items():
            self._last[cid] = _Last(frame_index, box.bbox)
            out.append(box if box.track_id == cid else replace(box, track_id=cid))
        return sorted(out, key=lambda b: b.track_id)

    def _match(self, frame_index: int, bbox: Box, visible: dict[int, Box]) -> int | None:
        best: tuple[float, int] | None = None
        for cid, other in visible.items():
            score = ios(bbox, other)
            if score >= self.contain and (best is None or (score, -cid) > (best[0], -best[1])):
                best = (score, cid)
        if best is not None:
            return best[1]
        for cid, last in self._last.items():
            if cid in visible or frame_index - last.frame > self.max_gap:
                continue
            score = ios(bbox, last.bbox)
            if score >= self.reborn_overlap and (best is None or (score, -cid) > (best[0], -best[1])):
                best = (score, cid)
        return None if best is None else best[1]

    @staticmethod
    def _prefer(candidate: HasTrack, current: HasTrack, cid: int) -> bool:
        if (candidate.track_id == cid) != (current.track_id == cid):
            return candidate.track_id == cid
        return candidate.confidence > current.confidence
