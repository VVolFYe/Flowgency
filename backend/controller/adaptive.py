"""Deterministic, safety-bounded green extension for the synthetic junction.

The policy never selects an arbitrary signal string or skips a SUMO phase. It
only requests the remaining duration of the *current* green. SUMO's configured
yellow and all-red phases remain authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


PHASE_APPROACHES = {
    "north_south_green": ("northbound_in", "southbound_in"),
    "east_west_green": ("eastbound_in", "westbound_in"),
}
OPPOSITE = {
    "north_south_green": "east_west_green",
    "east_west_green": "north_south_green",
}


@dataclass(frozen=True)
class AdaptiveConfig:
    min_green_s: float = 10.0
    max_green_s: float = 45.0
    max_red_s: float = 40.0
    switch_margin_vehicles: float = 2.0
    sustained_samples: int = 3
    smoothing: float = 0.35

    def __post_init__(self) -> None:
        if not 0 < self.min_green_s < self.max_green_s:
            raise ValueError("green bounds must satisfy 0 < min < max")
        if self.max_red_s <= self.min_green_s:
            raise ValueError("max_red_s must exceed min_green_s")
        if self.switch_margin_vehicles < 0 or self.sustained_samples < 1:
            raise ValueError("switch margin and sustained samples must be nonnegative/positive")
        if not 0 < self.smoothing <= 1:
            raise ValueError("smoothing must be in (0, 1]")


@dataclass(frozen=True)
class AdaptiveState:
    phase_id: str | None = None
    phase_started_s: float = 0.0
    last_green_ns_s: float = 0.0
    last_green_ew_s: float = 0.0
    smoothed_ns: float | None = None
    smoothed_ew: float | None = None
    switch_samples: int = 0


@dataclass(frozen=True)
class AdaptiveDecision:
    remaining_green_s: float | None
    reason: str
    current_score: float | None = None
    opposing_score: float | None = None


def decide(
    snapshot: dict[str, Any], state: AdaptiveState, config: AdaptiveConfig
) -> tuple[AdaptiveDecision, AdaptiveState]:
    """Evaluate one snapshot; return a decision and new immutable policy state.

    Missing or invalid queue measurements yield no command, preserving the
    installed SUMO plan. A one-second request completes the current green on
    the next step; a two-second request keeps it alive for reevaluation.
    """
    phase = snapshot.get("current_phase_id")
    now = float(snapshot["simulation_time_s"])
    if phase not in PHASE_APPROACHES:
        return AdaptiveDecision(None, "clearance_phase_owned_by_sumo"), state
    expected_state = "GrGr" if phase == "north_south_green" else "rGrG"
    if snapshot.get("traffic_light_state") != expected_state:
        return AdaptiveDecision(None, "unexpected_signal_state_use_fixed_plan"), state

    queues = snapshot.get("queue_lengths_by_approach", {})
    counts: dict[str, int] = {}
    for approach in (*PHASE_APPROACHES["north_south_green"], *PHASE_APPROACHES["east_west_green"]):
        entry = queues.get(approach)
        value = entry.get("vehicles") if isinstance(entry, dict) else None
        if type(value) is not int or value < 0 or entry.get("measurement") != "sumo_halting_number":
            return AdaptiveDecision(None, "missing_or_invalid_queue_use_fixed_plan"), state
        counts[approach] = value

    if phase != state.phase_id or now < state.phase_started_s:
        state = replace(state, phase_id=phase, phase_started_s=now, switch_samples=0)
    ns = sum(counts[a] for a in PHASE_APPROACHES["north_south_green"])
    ew = sum(counts[a] for a in PHASE_APPROACHES["east_west_green"])
    alpha = config.smoothing
    smooth_ns = float(ns) if state.smoothed_ns is None else alpha * ns + (1 - alpha) * state.smoothed_ns
    smooth_ew = float(ew) if state.smoothed_ew is None else alpha * ew + (1 - alpha) * state.smoothed_ew
    state = replace(
        state,
        smoothed_ns=smooth_ns,
        smoothed_ew=smooth_ew,
        last_green_ns_s=now if phase == "north_south_green" else state.last_green_ns_s,
        last_green_ew_s=now if phase == "east_west_green" else state.last_green_ew_s,
    )
    elapsed = now - state.phase_started_s
    current = smooth_ns if phase == "north_south_green" else smooth_ew
    opposing = smooth_ew if phase == "north_south_green" else smooth_ns
    opposing_last = state.last_green_ew_s if phase == "north_south_green" else state.last_green_ns_s

    if elapsed >= config.max_green_s:
        reason, remaining = "maximum_green_reached", 1.0
    elif elapsed < config.min_green_s:
        reason, remaining = "minimum_green_protected", 2.0
    elif now - opposing_last >= config.max_red_s:
        reason, remaining = "opposing_approach_anti_starvation", 1.0
    else:
        sustained = state.switch_samples + 1 if opposing >= current + config.switch_margin_vehicles else 0
        state = replace(state, switch_samples=sustained)
        if sustained >= config.sustained_samples:
            reason, remaining = "sustained_opposing_queue_advantage", 1.0
        else:
            reason, remaining = "hold_green_and_reevaluate", 2.0
    return AdaptiveDecision(remaining, reason, current, opposing), state
