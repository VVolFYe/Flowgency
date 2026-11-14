"""Deterministic, bounded announcements from confirmed simulation state."""

from __future__ import annotations

from collections import deque
from hashlib import sha256
from math import isfinite
from typing import Any

from backend.controller.adaptive import PHASE_APPROACHES
from backend.controller.emergency import EXPECTED_GREEN_STATES

MESSAGES = {
    "adaptive.plan_selected": (
        "A new green timing plan has been selected for the current traffic.",
        "A fost ales un nou plan pentru duratele de verde, pe baza traficului măsurat.",
    ),
    "traffic.congestion_sustained": (
        "Traffic is building near the intersection.",
        "Traficul se aglomerează în apropierea intersecției.",
    ),
    "emergency.requested": (
        "Emergency vehicle approaching. Safe signal priority requested.",
        "Se apropie un vehicul de intervenție. S-a solicitat prioritate la semafor, cu respectarea timpilor de siguranță.",
    ),
    "emergency.already_green": (
        "Emergency vehicle approaching. Its approach already has a green signal.",
        "Se apropie un vehicul de intervenție. Direcția sa are deja verde.",
    ),
    "emergency.green_confirmed": (
        "Green signal confirmed for the emergency approach.",
        "S-a confirmat verde pentru direcția vehiculului de intervenție.",
    ),
    "emergency.request_ended": (
        "Emergency priority request ended.",
        "Solicitarea de prioritate pentru vehiculul de intervenție s-a încheiat.",
    ),
}


class VoiceAlertPolicy:
    """Produce one-time traffic alerts; never call TraCI or a TTS provider."""

    def __init__(
        self,
        *,
        language: str = "en",
        material_green_change_s: float = 10.0,
        routine_cooldown_s: float = 60.0,
        congestion_threshold_vehicles: int | None = None,
        congestion_sustain_s: float = 10.0,
        history_size: int = 12,
    ) -> None:
        if language not in {"en", "ro"}:
            raise ValueError("unsupported voice language")
        if material_green_change_s <= 0 or routine_cooldown_s < 0 or congestion_sustain_s <= 0:
            raise ValueError("invalid voice alert timing")
        if congestion_threshold_vehicles is not None and congestion_threshold_vehicles <= 0:
            raise ValueError("congestion threshold must be positive")
        self.language = language
        self.material_green_change_s = material_green_change_s
        self.routine_cooldown_s = routine_cooldown_s
        self.congestion_threshold_vehicles = congestion_threshold_vehicles
        self.congestion_sustain_s = congestion_sustain_s
        self._history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._emitted_ids: set[str] = set()
        self._run_id: str | None = None
        self._active_vehicle_id: str | None = None
        self._green_announced = False
        self._previous_plan: dict[str, float] | None = None
        self._last_routine_time = float("-inf")
        self._high_queue_since: float | None = None
        self._congestion_announced = False

    def _reset(self, run_id: str) -> None:
        self._history.clear()
        self._emitted_ids.clear()
        self._run_id = run_id
        self._active_vehicle_id = None
        self._green_announced = False
        self._previous_plan = None
        self._last_routine_time = float("-inf")
        self._high_queue_since = None
        self._congestion_announced = False

    def _emit(self, message_id: str, subject: str, now: float) -> dict[str, Any] | None:
        assert self._run_id is not None
        text = MESSAGES[message_id][0 if self.language == "en" else 1]
        event_id = sha256(f"{self._run_id}|{subject}|{message_id}".encode()).hexdigest()[:24]
        if event_id in self._emitted_ids:
            return None
        alert = {
            "event_id": event_id,
            "run_id": self._run_id,
            "message_id": message_id,
            "text": text,
            "language": self.language,
            "simulation_time_s": now,
            "priority": "emergency" if message_id.startswith("emergency.") else "routine",
        }
        self._history.append(alert)
        self._emitted_ids.add(event_id)
        return alert

    @staticmethod
    def _confirmed_green(snapshot: dict[str, Any], approach: str | None) -> bool:
        phase = snapshot.get("current_phase_id")
        return bool(
            approach
            and phase in PHASE_APPROACHES
            and approach in PHASE_APPROACHES[phase]
            and snapshot.get("traffic_light_state") == EXPECTED_GREEN_STATES[phase]
        )

    def observe(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        """Add alerts to a snapshot and return only newly emitted alerts."""
        run_id = snapshot.get("run_id")
        now = snapshot.get("simulation_time_s")
        if not isinstance(run_id, str) or not isinstance(now, (int, float)) or not isfinite(now):
            snapshot["voice_alerts"] = []
            return []
        if run_id != self._run_id:
            self._reset(run_id)
        new: list[dict[str, Any]] = []
        def announce(message_id: str, subject: str) -> None:
            alert = self._emit(message_id, subject, now)
            if alert is not None:
                new.append(alert)

        emergency = snapshot.get("emergency_priority") or {}
        vehicle_id = emergency.get("active_vehicle_id")
        approach = emergency.get("active_approach")
        green = self._confirmed_green(snapshot, approach)
        if vehicle_id != self._active_vehicle_id:
            if self._active_vehicle_id is not None:
                announce("emergency.request_ended", self._active_vehicle_id)
            self._active_vehicle_id = vehicle_id
            self._green_announced = False
            if vehicle_id is not None:
                message = "emergency.already_green" if green else "emergency.requested"
                announce(message, vehicle_id)
                self._green_announced = green
        elif vehicle_id is not None and green and not self._green_announced:
            announce("emergency.green_confirmed", vehicle_id)
            self._green_announced = True

        decision = (snapshot.get("adaptive_control") or {}).get("last_cycle_decision") or {}
        plan = decision.get("green_durations_s")
        if isinstance(plan, dict) and plan:
            current = {str(key): float(value) for key, value in plan.items()}
            previous = self._previous_plan
            if previous is not None and previous.keys() == current.keys() and not vehicle_id and not new:
                change = max(abs(current[key] - previous[key]) for key in current)
                if change >= self.material_green_change_s and now - self._last_routine_time >= self.routine_cooldown_s:
                    announce("adaptive.plan_selected", f"cycle-{now}")
                    self._last_routine_time = now
            self._previous_plan = current

        threshold = self.congestion_threshold_vehicles
        queue = snapshot.get("network_queue") or {}
        count = queue.get("vehicles")
        if threshold is not None and isinstance(count, int) and queue.get("measurement") == "sumo_halting_number_unique_controlled_lanes":
            if count >= threshold:
                if self._high_queue_since is None:
                    self._high_queue_since = now
                if (
                    not self._congestion_announced
                    and not vehicle_id
                    and not new
                    and now - self._high_queue_since >= self.congestion_sustain_s
                    and now - self._last_routine_time >= self.routine_cooldown_s
                ):
                    announce("traffic.congestion_sustained", f"queue-{self._high_queue_since}")
                    self._congestion_announced = True
                    self._last_routine_time = now
            elif count <= threshold * 0.6:
                self._high_queue_since = None
                self._congestion_announced = False

        snapshot["voice_alerts"] = list(self._history)
        return new

    def get(self, event_id: str) -> dict[str, Any] | None:
        return next((alert.copy() for alert in self._history if alert["event_id"] == event_id), None)
