"""Pure emergency preference for the verified synthetic two-axis signal.

This policy requests only the remaining duration of the current green. SUMO
owns the normal phase sequence and all yellow/all-red clearance intervals.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .adaptive import PHASE_APPROACHES


EMERGENCY_TYPES = frozenset({"ambulance", "fire_brigade", "police"})
EXPECTED_GREEN_STATES = {
    "north_south_green": "GrGr",
    "east_west_green": "rGrG",
}


@dataclass(frozen=True)
class EmergencyRequest:
    vehicle_id: str
    vehicle_type: str
    approach: str
    first_seen_s: float


@dataclass(frozen=True)
class EmergencyDecision:
    remaining_green_s: float | None
    reason: str
    active_vehicle_id: str | None
    active_approach: str | None


def decide_emergency(
    *,
    phase_id: str | None,
    signal_state: str | None,
    phase_elapsed_s: float,
    requests: tuple[EmergencyRequest, ...],
    active_vehicle_id: str | None = None,
    min_green_s: float = 10.0,
) -> EmergencyDecision:
    """Prefer one active vehicle, then the earliest observed request.

    A conflicting green is ended only after its full minimum. A compatible
    green is held in two-second increments until the vehicle leaves the
    intersection, even beyond the normal maximum. No command is issued in a
    clearance phase or for an unexpected signal state.
    """
    if not isfinite(phase_elapsed_s) or phase_elapsed_s < 0:
        raise ValueError("phase_elapsed_s must be finite and nonnegative")
    if not isfinite(min_green_s) or min_green_s <= 0:
        raise ValueError("min_green_s must be finite and positive")
    for request in requests:
        if (
            not request.vehicle_id
            or request.vehicle_type not in EMERGENCY_TYPES
            or request.approach not in {a for group in PHASE_APPROACHES.values() for a in group}
            or not isfinite(request.first_seen_s)
            or request.first_seen_s < 0
        ):
            raise ValueError("invalid emergency request")
    if not requests:
        return EmergencyDecision(None, "no_emergency_request", None, None)

    selected = next((r for r in requests if r.vehicle_id == active_vehicle_id), None)
    if selected is None:
        selected = min(requests, key=lambda r: (r.first_seen_s, r.vehicle_id))

    if phase_id not in PHASE_APPROACHES:
        return EmergencyDecision(None, "clearance_phase_owned_by_sumo", selected.vehicle_id, selected.approach)
    if signal_state != EXPECTED_GREEN_STATES[phase_id]:
        return EmergencyDecision(None, "unexpected_signal_state_use_fixed_plan", selected.vehicle_id, selected.approach)
    if selected.approach in PHASE_APPROACHES[phase_id]:
        return EmergencyDecision(2.0, "hold_compatible_green_for_emergency", selected.vehicle_id, selected.approach)
    if phase_elapsed_s < min_green_s:
        return EmergencyDecision(2.0, "minimum_green_protected_before_emergency", selected.vehicle_id, selected.approach)
    return EmergencyDecision(0.0, "request_normal_clearance_for_emergency", selected.vehicle_id, selected.approach)
