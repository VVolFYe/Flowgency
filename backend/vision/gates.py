"""Gate triggers -> events (contract I) and per-second counts (contract J). Pure Python and causal.

Input is the tracker output already reduced to one counting point per track per frame (box centre for top-down
scenes). Every decision at frame ``f`` uses only frames ``<= f``, so the same rules can run live; an event's
``frame`` is the frame at which it was decided. Everything is deterministic. All parameters are scene fields.

Gate rule
---------
A track triggers a gate **once**, at the first frame ``f`` where its counting point has been inside the gate
polygon (boundary included) in at least ``gate_min_inside`` of the last ``gate_window_frames`` *video* frames
``f - window + 1 .. f`` (default 2 of 3). A frame in which the track was not observed counts as not inside.

Positions, not motion, exclude parked cars
------------------------------------------
Gates and approach regions (convex hull of an arm's ``in.far`` and ``in.stop`` gates) cover travel lanes only, so
a car in a parking spot is never inside one. Nothing here looks at future frames or at whole-clip motion.

Confirmation
------------
A track counts towards an approach only once it has been observed in ``min_track_frames`` frames. A far-gate
trigger by a younger track is held (logged as ``unconfirmed``) and applied when the track is confirmed, with the
event at that frame; a short fragment that dies first never creates an arrival.

Warm-up (starting offset)
-------------------------
At warm-up frame ``W = round(warmup_s * fps)``, every confirmed track observed in the last ``gate_window_frames``
frames is placed where it was last seen: inside an arm's approach region -> that arm's initial count; inside the
junction (hull of all stop and out gates, outside every approach region) -> initial junction occupancy. A track
that crossed a stop gate before ``W`` (and no out gate) is in the junction. Every gate trigger before ``W`` is
logged as suppressed (``warmup``); counts lines before ``W`` carry no arms and ``in_intersection`` null (unknown).

Approach membership
-------------------
A track is counted on at most one approach at a time and joins an approach at most once (so each track has at
most one ``approach_entered``). It joins by

* crossing the arm's far gate -> ``approach_entered`` with ``via: "far_gate"``;
* entering the arm's approach region without crossing its far gate, e.g. pulling out of a parking spot or being
  first detected (or re-identified) mid-approach -> ``approach_entered`` with ``via: "region"``. Only a confirmed
  track that has not entered the intersection and was never seen in the junction joins this way, once inside the
  region in ``gate_min_inside`` of the last ``gate_window_frames`` frames.

It stops being counted by

* crossing the arm's stop gate -> ``intersection_entered`` (a discharge);
* being at least ``region_leave_margin_px`` outside its region for ``region_leave_frames`` consecutive
  observations, e.g. turning into a parking spot -> ``approach_left`` with ``via: "region"`` (the margin keeps a car
  queued on the region's edge, whose box centre jitters across it, counted);
* not being observed for ``lost_s`` (longer than the tracker keeps a lost ID, so it cannot come back; a
  re-identified vehicle joins again under its new ID) -> ``approach_left`` with ``via: "lost"``;
* staying within ``obstruction_radius_px`` of one point inside its region for ``obstruction_s`` (longer than any
  red light) -> ``approach_left`` with ``via: "obstruction"``.

``vehicles_on_approach`` = tracks counted on the arm now = ``initial + entered_total - discharged_total -
left_total``; it cannot go negative. ``discharged_total`` counts intersection entries by tracks counted on that
approach; an ``intersection_entered`` by an uncounted track (e.g. a fragment younger than ``min_track_frames``)
changes no approach count.

Intersection
------------
A track enters the intersection **once**: its first stop-gate trigger emits ``intersection_entered``; a later one
(e.g. a left-turner clipping another arm's stop gate) is suppressed as ``already_entered``. ``<arm>_out`` emits
``intersection_exited`` with ``origin_arm`` = the arm of the track's ``intersection_entered``, or ``null`` when there
is none (``in_junction_at_start`` / ``no_entry_seen``); it is never guessed.
``in_intersection = max(0, initial junction + intersection_entered - out triggers)``; each trigger that leaves the
raw value below zero is logged as a clamp. It is ``null`` unless all four stop and four out gates exist.
"""

from __future__ import annotations

import math
from collections import Counter, deque
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from backend.models.gates import ApproachGateCounts, GateCounts, GateEvent

from .geometry import Point, distance_to_polygon, point_in_polygon
from .scene import ARMS, GATE_IDS, SceneConfig, gate_arm, gate_kind

EVENT_FOR_KIND = {"in.far": "approach_entered", "in.stop": "intersection_entered", "out": "intersection_exited"}


@dataclass(frozen=True)
class TrackPoint:
    track_id: int
    point: Point


@dataclass(frozen=True)
class GateTrigger:
    track_id: int
    gate_id: str
    frame: int
    # None = applied. "warmup" | "unconfirmed" | "initial_on_approach" | "already_on_approach" | "already_joined"
    # | "initial_in_junction" | "already_entered"
    suppressed: str | None = None
    point: Point | None = None  # counting point at the trigger frame
    applied_frame: int | None = None  # a held far-gate trigger: frame at which the track was confirmed


@dataclass(frozen=True)
class InitialState:
    warmup_frame: int
    min_track_frames: int
    approach_tracks: dict[str, tuple[int, ...]]  # arm -> confirmed track IDs in its approach region at warm-up
    junction_tracks: tuple[int, ...] | None  # None when the junction region is unknown

    def approach_counts(self) -> dict[str, int]:
        return {arm: len(ids) for arm, ids in self.approach_tracks.items()}


@dataclass(frozen=True)
class Clamp:
    frame: int
    t_s: float
    quantity: str  # "in_intersection"
    arm: str | None
    raw: int
    track_id: int
    gate_id: str


@dataclass
class GateRun:
    events: list[dict]
    counts: list[dict]
    triggers: list[GateTrigger]
    initial: InitialState
    clamps: list[Clamp]
    origin_null: Counter = field(default_factory=Counter)  # reason -> number of exits with origin_arm null

    def triggers_by_gate(self, include_suppressed: bool = False) -> dict[str, int]:
        out = {g: 0 for g in GATE_IDS}
        for trigger in self.triggers:
            if include_suppressed or trigger.suppressed is None:
                out[trigger.gate_id] += 1
        return out

    def events_by_type(self) -> dict[str, int]:
        """``event`` or ``event/via`` -> number of events."""
        return dict(sorted(Counter(e["event"] + (f"/{e['via']}" if "via" in e else "") for e in self.events).items()))


def time_s(frame: int, fps: float) -> float:
    return round(frame / fps, 3)


class _GateIndex:
    """Gates with bounding boxes for a cheap pre-check."""

    def __init__(self, scene: SceneConfig) -> None:
        self.gates = []
        for gate_id, poly in scene.gates.items():
            xs, ys = [p[0] for p in poly], [p[1] for p in poly]
            self.gates.append((gate_id, poly, (min(xs), min(ys), max(xs), max(ys))))

    def inside(self, point: Point) -> list[str]:
        x, y = point
        return [g for g, poly, (x1, y1, x2, y2) in self.gates
                if x1 <= x <= x2 and y1 <= y <= y2 and point_in_polygon(point, poly)]


class Locator:
    """``SceneConfig.locate`` with the region hulls computed once."""

    def __init__(self, scene: SceneConfig) -> None:
        self.regions = scene.approach_regions()
        self.junction = scene.junction_region()
        self._boxes = {name: _bbox(poly) for name, poly in
                       [*self.regions.items(), *([("junction", self.junction)] if self.junction else [])]}

    def locate(self, point: Point) -> str | None:
        """``<arm>`` if in that approach region, ``"junction"`` if in the junction, else ``None``."""
        for arm, region in self.regions.items():
            if _in_box(point, self._boxes[arm]) and point_in_polygon(point, region):
                return arm
        if self.junction is not None and _in_box(point, self._boxes["junction"]) \
                and point_in_polygon(point, self.junction):
            return "junction"
        return None


def _bbox(poly: Sequence[Point]) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _in_box(p: Point, box: tuple[float, float, float, float]) -> bool:
    return box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]


def detect_triggers(scene: SceneConfig, frames: Sequence[tuple[int, Sequence[TrackPoint]]],
                    min_inside: int | None = None, window: int | None = None) -> list[GateTrigger]:
    """Apply the ``min_inside``-of-``window`` gate rule (default: the scene's); frames in increasing order."""
    min_inside = scene.gate_min_inside if min_inside is None else min_inside
    window = scene.gate_window_frames if window is None else window
    if not 1 <= min_inside <= window:
        raise ValueError(f"gate rule needs 1 <= min_inside <= window, got {min_inside} of {window}")
    index = _GateIndex(scene)
    recent: dict[tuple[int, str], list[int]] = {}  # frames inside the gate within the window
    fired: set[tuple[int, str]] = set()
    out: list[GateTrigger] = []
    previous = -1
    for frame, points in frames:
        if frame <= previous:
            raise ValueError(f"frames must be strictly increasing (got {frame} after {previous})")
        previous = frame
        for tp in sorted(points, key=lambda p: p.track_id):
            for gate_id in index.inside(tp.point):
                key = (tp.track_id, gate_id)
                if key in fired:
                    continue
                inside = [f for f in recent.get(key, ()) if f > frame - window] + [frame]
                if len(inside) >= min_inside:
                    fired.add(key)
                    recent.pop(key, None)
                    out.append(GateTrigger(tp.track_id, gate_id, frame, point=tp.point))
                else:
                    recent[key] = inside
    order = {g: i for i, g in enumerate(GATE_IDS)}
    return sorted(out, key=lambda t: (t.frame, t.track_id, order[t.gate_id]))


@dataclass
class _Track:
    n_obs: int = 0
    last_seen: int = -1
    point: Point = (0.0, 0.0)
    locs: deque = field(default_factory=deque)  # (frame, location) of observations in the last window frames
    member: str | None = None  # arm it is counted on now
    joined: bool = False  # has joined an approach (at most once)
    initial: bool = False  # in the warm-up offset of an approach
    entered: bool = False  # past a stop line (intersection_entered, or before warm-up)
    entry_arm: str | None = None  # arm of its intersection_entered event
    initial_junction: bool = False
    warm_entered: bool = False  # crossed a stop gate before warm-up
    seen_junction: bool = False
    outside_streak: int = 0
    anchor: Point | None = None
    anchor_frame: int = 0
    held_far: int | None = None  # index into the trigger log of a far-gate trigger awaiting confirmation


class _Engine:
    """Frame-by-frame state machine; ``step`` uses only the frame given and earlier state."""

    def __init__(self, scene: SceneConfig, fps: float, model_id: str) -> None:
        self.scene, self.fps, self.model_id = scene, fps, model_id
        self.loc = Locator(scene)
        self.arms = [a for a in ARMS if a in self.loc.regions]
        self.junction_known = self.loc.junction is not None
        self.window, self.min_inside = scene.gate_window_frames, scene.gate_min_inside
        self.warm_frame = round(scene.warmup_s * fps)
        self.need = scene.min_track_frames
        self.lost_frames = max(1, round(scene.lost_s * fps))
        self.obstruction_frames = max(1, round(scene.obstruction_s * fps))
        self.tracks: dict[int, _Track] = {}
        self.log: list[GateTrigger] = []
        self.events: list[dict] = []
        self.entered = dict.fromkeys(self.arms, 0)
        self.discharged = dict.fromkeys(self.arms, 0)
        self.left = dict.fromkeys(self.arms, 0)
        self.initial: InitialState | None = None
        self.initial_junction = 0
        self.stops = self.outs = 0
        self.clamps: list[Clamp] = []
        self.origin_null: Counter[str] = Counter()
        self._warm_stop: set[int] = set()
        self._warm_out: set[int] = set()

    # --- events ---------------------------------------------------------------
    def _emit(self, frame: int, track_id: int, event: str, arm: str, **extra: Any) -> None:
        payload = {"event": event, "track_id": track_id, "arm": arm, "t_s": time_s(frame, self.fps), "frame": frame,
                   "model_id": self.model_id, **extra}
        self.events.append(GateEvent.model_validate(payload).to_contract_dict())

    def _join(self, frame: int, tid: int, tr: _Track, arm: str, via: str) -> None:
        tr.joined = True
        if arm in self.entered:  # an arm without an approach region has no count
            tr.member, tr.outside_streak, tr.anchor = arm, 0, None
            self.entered[arm] += 1
        self._emit(frame, tid, "approach_entered", arm, via=via)

    def _leave(self, frame: int, tid: int, tr: _Track, via: str) -> None:
        arm, tr.member, tr.anchor = tr.member, None, None
        self.left[arm] += 1
        self._emit(frame, tid, "approach_left", arm, via=via)

    # --- per frame ------------------------------------------------------------
    def step(self, frame: int, points: Sequence[TrackPoint], triggers: Sequence[GateTrigger]) -> None:
        observed = sorted(points, key=lambda p: p.track_id)
        for tp in observed:
            tr = self.tracks.setdefault(tp.track_id, _Track())
            where = self.loc.locate(tp.point)
            tr.n_obs, tr.last_seen, tr.point = tr.n_obs + 1, frame, tp.point
            tr.locs.append((frame, where))
            while tr.locs[0][0] <= frame - self.window:
                tr.locs.popleft()
            tr.seen_junction |= where == "junction"
        if self.initial is None and frame >= self.warm_frame:
            self._warm_up(frame)
        if self.initial is None:
            for t in triggers:
                kind = gate_kind(t.gate_id)
                (self._warm_stop if kind == "in.stop" else self._warm_out if kind == "out" else set()).add(t.track_id)
                self.log.append(replace(t, suppressed="warmup"))
            return
        for tid in sorted(self.tracks):
            tr = self.tracks[tid]
            if tr.member is not None and frame - tr.last_seen > self.lost_frames:
                self._leave(frame, tid, tr, "lost")
        by_track: dict[int, list[GateTrigger]] = {}
        for t in triggers:
            by_track.setdefault(t.track_id, []).append(t)
        for tp in observed:
            tid, tr = tp.track_id, self.tracks[tp.track_id]
            for t in by_track.get(tid, ()):
                self._trigger(frame, tid, tr, t)
            self._confirm_held(frame, tid, tr)
            self._region_rules(frame, tid, tr)

    def _warm_up(self, frame: int) -> None:
        approach: dict[str, list[int]] = {arm: [] for arm in self.arms}
        junction: list[int] = []
        for tid in sorted(self.tracks):
            tr = self.tracks[tid]
            if tid in self._warm_stop:
                tr.entered = tr.warm_entered = True
            if tr.n_obs < self.need or tr.last_seen <= frame - self.window or tid in self._warm_out:
                continue
            where = tr.locs[-1][1]
            if tid in self._warm_stop or where == "junction":
                if self.junction_known:
                    junction.append(tid)
                    tr.initial_junction = tr.entered = True
            elif where in approach:
                approach[where].append(tid)
                tr.member, tr.joined, tr.initial = where, True, True
        self.initial_junction = len(junction)
        self.initial = InitialState(frame, self.need, {a: tuple(ids) for a, ids in approach.items()},
                                    tuple(junction) if self.junction_known else None)

    def _trigger(self, frame: int, tid: int, tr: _Track, t: GateTrigger) -> None:
        kind, arm = gate_kind(t.gate_id), gate_arm(t.gate_id)
        reason = None
        if kind == "in.far":
            if tr.entered:
                reason = "already_entered"
            elif tr.member == arm:
                reason = "initial_on_approach" if tr.initial else "already_on_approach"
            elif tr.joined:
                reason = "already_joined"
            elif tr.n_obs < self.need:
                reason = "unconfirmed"
                tr.held_far = len(self.log)
            else:
                if tr.member is not None:
                    self._leave(frame, tid, tr, "region")
                self._join(frame, tid, tr, arm, "far_gate")
        elif kind == "in.stop":
            if tr.initial_junction:
                reason = "initial_in_junction"
            elif tr.entered:
                reason = "already_entered"
            else:
                if tr.member is not None and tr.member != arm:
                    self._leave(frame, tid, tr, "region")
                tr.entered, tr.entry_arm, tr.held_far = True, arm, None
                self.stops += 1
                if tr.member == arm:
                    self.discharged[arm] += 1
                    tr.member = None
                self._emit(frame, tid, "intersection_entered", arm)
        else:
            if tr.member is not None:
                self._leave(frame, tid, tr, "region")
            origin = tr.entry_arm
            if origin is None:
                self.origin_null["in_junction_at_start" if tr.initial_junction or tr.warm_entered
                                 else "no_entry_seen"] += 1
            self.outs += 1
            self._emit(frame, tid, "intersection_exited", arm, origin_arm=origin)
            raw = self.initial_junction + self.stops - self.outs
            if self.junction_known and raw < 0:
                self.clamps.append(Clamp(frame, time_s(frame, self.fps), "in_intersection", None, raw, tid, t.gate_id))
        self.log.append(replace(t, suppressed=reason))

    def _confirm_held(self, frame: int, tid: int, tr: _Track) -> None:
        if tr.held_far is None or tr.n_obs < self.need:
            return
        index, tr.held_far = tr.held_far, None
        if tr.entered or tr.joined:
            return
        held = self.log[index]
        if tr.member is not None:
            self._leave(frame, tid, tr, "region")
        self._join(frame, tid, tr, gate_arm(held.gate_id), "far_gate")
        self.log[index] = replace(held, suppressed=None, applied_frame=frame)

    def _region_rules(self, frame: int, tid: int, tr: _Track) -> None:
        where = tr.locs[-1][1]
        if tr.member is None:
            if (not tr.joined and not tr.entered and not tr.seen_junction and tr.held_far is None
                    and tr.n_obs >= self.need and where in self.entered
                    and sum(1 for _, w in tr.locs if w == where) >= self.min_inside):
                self._join(frame, tid, tr, where, "region")
            return
        if where != tr.member:
            far = distance_to_polygon(tr.point, self.loc.regions[tr.member]) >= self.scene.region_leave_margin_px
            tr.outside_streak = tr.outside_streak + 1 if far else 0
            if tr.outside_streak >= self.scene.region_leave_frames:
                self._leave(frame, tid, tr, "region")
            return
        tr.outside_streak = 0
        if tr.anchor is None or math.dist(tr.point, tr.anchor) > self.scene.obstruction_radius_px:
            tr.anchor, tr.anchor_frame = tr.point, frame
        elif frame - tr.anchor_frame >= self.obstruction_frames:
            self._leave(frame, tid, tr, "obstruction")

    # --- counts ---------------------------------------------------------------
    def snapshot(self) -> dict | None:
        """The published state now, or None (unknown) before warm-up."""
        if self.initial is None:
            return None
        init = self.initial.approach_counts()
        approaches = {}
        for a in self.arms:
            on = init[a] + self.entered[a] - self.discharged[a] - self.left[a]
            assert on >= 0, (a, on)
            approaches[a] = ApproachGateCounts(vehicles_on_approach=on, entered_total=self.entered[a],
                                               discharged_total=self.discharged[a], left_total=self.left[a])
        junction = max(0, self.initial_junction + self.stops - self.outs) if self.junction_known else None
        return {"approaches": approaches, "in_intersection": junction}


def run_gates(
    scene: SceneConfig,
    frames: Sequence[tuple[int, Sequence[TrackPoint]]],
    *,
    fps: float,
    frame_count: int,
    model_id: str,
) -> GateRun:
    """Events and per-second counts for one clip. ``frames``: ``(frame_index, points)`` in increasing order.

    Causal: truncating ``frames`` after frame ``f`` leaves every event with ``frame <= f`` and every counts line
    with ``t_s <= f / fps`` unchanged.
    """
    if fps <= 0 or frame_count <= 0:
        raise ValueError("fps and frame_count must be positive")
    frames = list(frames)
    triggers_at: dict[int, list[GateTrigger]] = {}
    for t in detect_triggers(scene, frames):
        triggers_at.setdefault(t.frame, []).append(t)
    engine = _Engine(scene, fps, model_id)
    snapshots: list[tuple[int, dict | None]] = []
    for frame, points in frames:
        engine.step(frame, points, triggers_at.get(frame, ()))
        snapshots.append((frame, engine.snapshot()))
    if engine.initial is None:  # clip shorter than the warm-up: nothing was decided
        engine.initial = InitialState(engine.warm_frame, engine.need, {a: () for a in engine.arms},
                                      () if engine.junction_known else None)

    counts: list[dict] = []
    cursor, state = 0, None
    for second in range(math.floor((frame_count - 1) / fps) + 1):
        while cursor < len(snapshots) and snapshots[cursor][0] / fps <= second + 1e-9:
            state = snapshots[cursor][1]
            cursor += 1
        line = GateCounts(t_s=float(second), approaches=state["approaches"] if state else {},
                          in_intersection=state["in_intersection"] if state else None, model_id=model_id)
        counts.append(line.to_contract_dict())
    order = {g: i for i, g in enumerate(GATE_IDS)}
    triggers = sorted(engine.log, key=lambda t: (t.frame, t.track_id, order[t.gate_id]))
    return GateRun(engine.events, counts, triggers, engine.initial, engine.clamps, engine.origin_null)
