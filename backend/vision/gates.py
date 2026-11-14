"""Gate triggers -> events (contract I) and per-second counts (contract J). Pure Python.

Input is the tracker output already reduced to one counting point per track
per frame (box centre for top-down scenes). Everything here is deterministic.

Gate rule
---------
A track triggers a gate **once**, at the first frame ``f`` where its counting
point has been inside the gate polygon (boundary included) in at least
``min_inside`` of the last ``window`` *video* frames ``f - window + 1 .. f``
(scene fields ``gate_min_inside`` / ``gate_window_frames``, default 2 of 3, so
one missed frame is tolerated). A frame in which the track was not observed
counts as not inside. The trigger frame is always a frame where the point is
inside.

Gate -> event
-------------
``<arm>_in.far`` -> ``approach_entered``; ``<arm>_in.stop`` ->
``intersection_entered``; ``<arm>_out`` -> ``intersection_exited`` with
``origin_arm`` = the arm of the same track's earlier ``intersection_entered``.

A track enters the intersection **once**: only its first stop-gate trigger
emits ``intersection_entered`` (and counts as a discharge). A later stop-gate
trigger by the same track, e.g. a left-turner whose path clips another arm's
stop gate (south -> west on the youtube clip), is suppressed with reason
``already_entered``. So ``origin_arm`` is always the arm of the track's single
entry, or ``null`` when the track has no entry: the tracker lost the vehicle
(``no_entry_seen``) or it was already in the junction at the start
(``in_junction_at_start``). It is never guessed.

Initial state
-------------
Initial window = the first ``round(0.5 s * fps)`` frames. A track is *stable*
when observed in at least 75 % of them; its start location is where its first
observation in the window lies: an arm's approach region, the junction, or
neither (:meth:`SceneConfig.locate`). Stable tracks starting on an approach
form that arm's ``initial``; stable tracks starting in the junction form the
initial junction occupancy. To avoid counting a vehicle twice, an initial
approach vehicle's trigger of its own arm's far gate, and an initial junction
vehicle's trigger of any stop gate, are *suppressed*: kept in the trigger log,
but no event and no count. Suppressed triggers keep the counting point at the
trigger frame for the run log.

Counts
------
``vehicles_on_approach = max(0, initial + entered_total - discharged_total)``
and ``in_intersection = max(0, initial_junction + stop triggers - out
triggers)``, where the totals count unsuppressed triggers. Each trigger that
leaves a raw value below zero is logged as a clamp. The clamp is applied to
the formula's output only (no hidden state): later triggers move the raw value
back up. Arms appear only when both of their inbound gates exist;
``in_intersection`` is ``null`` unless all four stop and four out gates exist.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from backend.models.gates import ApproachGateCounts, GateCounts, GateEvent

from .geometry import Point, point_in_polygon
from .scene import ARMS, GATE_IDS, SceneConfig, gate_arm, gate_kind

INITIAL_WINDOW_S = 0.5
INITIAL_MIN_PRESENCE = 0.75
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
    suppressed: str | None = None  # "initial_on_approach" | "initial_in_junction" | "already_entered"
    point: Point | None = None  # counting point at the trigger frame


@dataclass(frozen=True)
class InitialState:
    window_frames: int
    min_observations: int
    approach_tracks: dict[str, tuple[int, ...]]  # arm -> stable track IDs starting on its approach
    junction_tracks: tuple[int, ...] | None  # None when the junction region is unknown

    def approach_counts(self) -> dict[str, int]:
        return {arm: len(ids) for arm, ids in self.approach_tracks.items()}


@dataclass(frozen=True)
class Clamp:
    frame: int
    t_s: float
    quantity: str  # "vehicles_on_approach" | "in_intersection"
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


def initial_state(scene: SceneConfig, frames: Sequence[tuple[int, Sequence[TrackPoint]]], fps: float,
                  window_s: float = INITIAL_WINDOW_S, min_presence: float = INITIAL_MIN_PRESENCE) -> InitialState:
    window = max(2, round(window_s * fps))
    need = math.ceil(min_presence * window)
    seen: Counter[int] = Counter()
    first: dict[int, Point] = {}
    for frame, points in frames:
        if frame >= window:
            break
        for tp in points:
            seen[tp.track_id] += 1
            first.setdefault(tp.track_id, tp.point)
    regions = scene.approach_regions()
    approach: dict[str, list[int]] = {arm: [] for arm in regions}
    junction_known = scene.junction_region() is not None
    junction: list[int] = []
    for track_id in sorted(seen):
        if seen[track_id] < need:
            continue
        where = scene.locate(first[track_id])
        if where in approach:
            approach[where].append(track_id)
        elif where == "junction" and junction_known:
            junction.append(track_id)
    return InitialState(
        window_frames=window,
        min_observations=need,
        approach_tracks={arm: tuple(ids) for arm, ids in approach.items()},
        junction_tracks=tuple(junction) if junction_known else None,
    )


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


def run_gates(
    scene: SceneConfig,
    frames: Sequence[tuple[int, Sequence[TrackPoint]]],
    *,
    fps: float,
    frame_count: int,
    model_id: str,
    window_s: float = INITIAL_WINDOW_S,
    min_presence: float = INITIAL_MIN_PRESENCE,
) -> GateRun:
    """Events and per-second counts for one clip. ``frames``: ``(frame_index, points)`` in order."""
    if fps <= 0 or frame_count <= 0:
        raise ValueError("fps and frame_count must be positive")
    frames = list(frames)
    initial = initial_state(scene, frames, fps, window_s, min_presence)
    on_approach = {tid: arm for arm, ids in initial.approach_tracks.items() for tid in ids}
    in_junction = set(initial.junction_tracks or ())

    triggers = []
    entered_via: dict[int, str] = {}  # track -> stop gate of its single intersection entry
    for t in detect_triggers(scene, frames):
        kind, arm = gate_kind(t.gate_id), gate_arm(t.gate_id)
        reason = None
        if kind == "in.far" and on_approach.get(t.track_id) == arm:
            reason = "initial_on_approach"
        elif kind == "in.stop" and t.track_id in in_junction:
            reason = "initial_in_junction"
        elif kind == "in.stop" and t.track_id in entered_via:
            reason = "already_entered"
        elif kind == "in.stop":
            entered_via[t.track_id] = t.gate_id
        triggers.append(GateTrigger(t.track_id, t.gate_id, t.frame, reason, t.point))

    # --- events ---------------------------------------------------------------
    events: list[dict] = []
    entries: dict[int, str] = {}
    origin_null: Counter[str] = Counter()
    for t in triggers:
        if t.suppressed:
            continue
        kind, arm = gate_kind(t.gate_id), gate_arm(t.gate_id)
        payload = {"event": EVENT_FOR_KIND[kind], "track_id": t.track_id, "arm": arm,
                   "t_s": time_s(t.frame, fps), "frame": t.frame, "model_id": model_id}
        if kind == "in.stop":
            entries[t.track_id] = arm  # at most one unsuppressed stop trigger per track
        elif kind == "out":
            payload["origin_arm"] = entries.get(t.track_id)
            if payload["origin_arm"] is None:
                origin_null["in_junction_at_start" if t.track_id in in_junction else "no_entry_seen"] += 1
        events.append(GateEvent.model_validate(payload).to_contract_dict())

    # --- counts ---------------------------------------------------------------
    arms = [a for a in ARMS if a in initial.approach_tracks]
    entered = dict.fromkeys(arms, 0)
    discharged = dict.fromkeys(arms, 0)
    initial_counts = initial.approach_counts()
    junction_known = initial.junction_tracks is not None
    stops = outs = 0
    clamps: list[Clamp] = []
    counts: list[dict] = []
    active = [t for t in triggers if t.suppressed is None]
    cursor = 0
    last_second = math.floor((frame_count - 1) / fps)
    for second in range(last_second + 1):
        while cursor < len(active) and active[cursor].frame / fps <= second + 1e-9:
            t = active[cursor]
            cursor += 1
            kind, arm = gate_kind(t.gate_id), gate_arm(t.gate_id)
            if kind == "in.far" and arm in entered:
                entered[arm] += 1
            elif kind == "in.stop":
                stops += 1
                if arm in discharged:
                    discharged[arm] += 1
                    raw = initial_counts[arm] + entered[arm] - discharged[arm]
                    if raw < 0:
                        clamps.append(Clamp(t.frame, time_s(t.frame, fps), "vehicles_on_approach", arm, raw,
                                            t.track_id, t.gate_id))
            elif kind == "out":
                outs += 1
            if junction_known and kind in ("in.stop", "out"):
                raw = len(in_junction) + stops - outs
                if raw < 0 and kind == "out":
                    clamps.append(Clamp(t.frame, time_s(t.frame, fps), "in_intersection", None, raw,
                                        t.track_id, t.gate_id))
        line = GateCounts(
            t_s=float(second),
            approaches={a: ApproachGateCounts(
                vehicles_on_approach=max(0, initial_counts[a] + entered[a] - discharged[a]),
                entered_total=entered[a], discharged_total=discharged[a]) for a in arms},
            in_intersection=max(0, len(in_junction) + stops - outs) if junction_known else None,
            model_id=model_id,
        )
        counts.append(line.to_contract_dict())
    return GateRun(events, counts, triggers, initial, clamps, origin_null)
