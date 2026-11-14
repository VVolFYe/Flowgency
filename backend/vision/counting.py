"""Directed line-crossing counter (pure geometry, no CV dependencies).

Counting rule
-------------
Each approach has a line segment ``p1-p2`` drawn across its lanes near the stop
line and an ``inbound_point`` on the side vehicles move *towards* when entering
the intersection ("downstream"). A track is counted for an approach when its
road contact point (bottom-centre of its box) moves from the upstream side (or
exactly on the line) to the downstream side, and that movement crosses the
segment within its extent. The counting point is configurable per camera
(``counting_point``): bottom-centre by default, box centre for top-down views.
Movements are measured between consecutive
*observations* of the track, so short tracker gaps still count.

* Outbound crossings (downstream -> upstream) are ignored.
* A track whose first observation is already downstream of a line is never
  counted for that approach, even if it later jitters back and forth.
* A track is counted at most once per approach.
* A counted track's class is its majority class over its whole life in the
  clip (ties: higher summed confidence, then alphabetical).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .detections import counting_point

VEHICLE_CLASSES = ("car", "motorcycle", "bus", "truck", "bicycle")

Point = tuple[float, float]


@dataclass(frozen=True)
class TrackedBox:
    track_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels

    @property
    def contact_point(self) -> Point:
        x1, _, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, y2)

    def point(self, mode: str = "bottom_center") -> Point:
        return counting_point(self.bbox, mode)


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


@dataclass(frozen=True)
class CountingLine:
    approach_id: str
    p1: Point
    p2: Point
    inbound_point: Point

    def __post_init__(self) -> None:
        if self.p1 == self.p2:
            raise ValueError(f"{self.approach_id}: degenerate line")
        if _cross(self.p1, self.p2, self.inbound_point) == 0:
            raise ValueError(f"{self.approach_id}: inbound point lies on the line")

    def side(self, point: Point) -> int:
        """+1 downstream (inbound side), -1 upstream, 0 exactly on the line."""
        value = _cross(self.p1, self.p2, point)
        if value == 0:
            return 0
        reference = _cross(self.p1, self.p2, self.inbound_point)
        return 1 if (value > 0) == (reference > 0) else -1

    def crosses_inbound(self, prev: Point, cur: Point) -> bool:
        if not (self.side(prev) <= 0 < self.side(cur)):
            return False
        d = (cur[0] - prev[0], cur[1] - prev[1])
        e = (self.p2[0] - self.p1[0], self.p2[1] - self.p1[1])
        denom = d[0] * e[1] - d[1] * e[0]
        if denom == 0:
            return False
        w = (self.p1[0] - prev[0], self.p1[1] - prev[1])
        u = (w[0] * d[1] - w[1] * d[0]) / denom  # position along p1->p2
        return 0.0 <= u <= 1.0


@dataclass
class _TrackStats:
    class_votes: Counter[str] = field(default_factory=Counter)
    class_conf: Counter[str] = field(default_factory=Counter)
    conf_sum: float = 0.0
    observations: int = 0
    last_point: Point | None = None
    first_side: dict[str, int] = field(default_factory=dict)

    @property
    def mean_confidence(self) -> float:
        return self.conf_sum / self.observations

    @property
    def majority_class(self) -> str:
        return min(
            self.class_votes,
            key=lambda c: (-self.class_votes[c], -self.class_conf[c], c),
        )


@dataclass(frozen=True)
class CrossingEvent:
    track_id: int
    approach_id: str
    frame_index: int


@dataclass(frozen=True)
class CountedTrack:
    track_id: int
    approach_id: str
    class_name: str
    mean_confidence: float
    frame_index: int


@dataclass(frozen=True)
class CountResult:
    counts_by_approach: dict[str, dict[str, int]]
    counted_tracks: tuple[CountedTrack, ...]
    confidence: float | None  # mean of per-track mean confidence over counted tracks


class LineCrossingCounter:
    """Feed per-frame tracked boxes, then read the per-approach counts."""

    def __init__(self, lines: Sequence[CountingLine], counting_point: str = "bottom_center") -> None:
        ids = [line.approach_id for line in lines]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate approach IDs")
        self.lines = tuple(lines)
        self.counting_point = counting_point
        TrackedBox(0, "car", 0.0, (0.0, 0.0, 1.0, 1.0)).point(counting_point)  # validate mode early
        self._tracks: dict[int, _TrackStats] = {}
        self._crossings: dict[tuple[int, str], int] = {}

    def update(self, frame_index: int, boxes: Iterable[TrackedBox]) -> list[CrossingEvent]:
        events: list[CrossingEvent] = []
        for box in boxes:
            if box.class_name not in VEHICLE_CLASSES:
                raise ValueError(f"unexpected class {box.class_name!r}")
            stats = self._tracks.setdefault(box.track_id, _TrackStats())
            stats.class_votes[box.class_name] += 1
            stats.class_conf[box.class_name] += box.confidence
            stats.conf_sum += box.confidence
            stats.observations += 1
            point = box.point(self.counting_point)
            for line in self.lines:
                stats.first_side.setdefault(line.approach_id, line.side(point))
                key = (box.track_id, line.approach_id)
                if (
                    key in self._crossings
                    or stats.last_point is None
                    or stats.first_side[line.approach_id] > 0
                ):
                    continue
                if line.crosses_inbound(stats.last_point, point):
                    self._crossings[key] = frame_index
                    events.append(CrossingEvent(box.track_id, line.approach_id, frame_index))
            stats.last_point = point
        return events

    def live_totals(self) -> dict[str, int]:
        totals = {line.approach_id: 0 for line in self.lines}
        for _, approach_id in self._crossings:
            totals[approach_id] += 1
        return totals

    def is_counted(self, track_id: int) -> bool:
        return any(tid == track_id for tid, _ in self._crossings)

    def result(self) -> CountResult:
        counts = {
            line.approach_id: {**{c: 0 for c in VEHICLE_CLASSES}, "total": 0}
            for line in self.lines
        }
        counted: list[CountedTrack] = []
        for (track_id, approach_id), frame_index in sorted(
            self._crossings.items(), key=lambda kv: (kv[1], kv[0])
        ):
            stats = self._tracks[track_id]
            cls = stats.majority_class
            counts[approach_id][cls] += 1
            counts[approach_id]["total"] += 1
            counted.append(
                CountedTrack(track_id, approach_id, cls, stats.mean_confidence, frame_index)
            )
        unique = {t.track_id: t.mean_confidence for t in counted}
        confidence = sum(unique.values()) / len(unique) if unique else None
        return CountResult(counts, tuple(counted), confidence)
