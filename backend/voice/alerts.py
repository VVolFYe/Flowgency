"""Deterministic, bounded announcements from confirmed simulation state."""

from __future__ import annotations

from collections import deque
from hashlib import sha256
from math import isfinite
from typing import Any

from backend.controller.adaptive import PHASE_APPROACHES
from backend.controller.emergency import EXPECTED_GREEN_STATES

MESSAGES = {
    "traffic.congestion_sustained": (
        "Traffic is building near the intersection.",
        "Traficul se aglomerează în apropierea intersecției.",
    ),
    "emergency.requested": (
        "Emergency vehicle approaching. Green light requested for its approach.",
        "Se apropie un vehicul de intervenție. S-a solicitat verde pentru direcția sa.",
    ),
    "emergency.already_green": (
        "Emergency vehicle approaching. Its approach already has a green signal.",
        "Se apropie un vehicul de intervenție. Direcția sa are deja verde.",
    ),
    "emergency.green_confirmed": (
        "Green signal confirmed for the emergency approach.",
        "S-a confirmat verde pentru direcția vehiculului de intervenție.",
    ),
    "emergency.detected": (
        "Emergency vehicle detected at intersection {intersection_id}.",
        "Vehicul de intervenție detectat la intersecția {intersection_id}.",
    ),
    "emergency.priority_activated": (
        "Emergency priority activated at intersection {intersection_id}.",
        "Prioritate de urgență activată la intersecția {intersection_id}.",
    ),
    "emergency.priority_completed": (
        "Emergency priority completed at intersection {intersection_id}.",
        "Prioritate de urgență încheiată la intersecția {intersection_id}.",
    ),
}


class VoiceAlertPolicy:
    """Produce one-time traffic alerts; never call TraCI or a TTS provider."""

    def __init__(
        self,
        *,
        language: str = "en",
        routine_cooldown_s: float = 60.0,
        congestion_threshold_vehicles: int | None = None,
        congestion_sustain_s: float = 10.0,
        history_size: int = 12,
    ) -> None:
        if language not in {"en", "ro"}:
            raise ValueError("unsupported voice language")
        if routine_cooldown_s < 0 or congestion_sustain_s <= 0:
            raise ValueError("invalid voice alert timing")
        if congestion_threshold_vehicles is not None and congestion_threshold_vehicles <= 0:
            raise ValueError("congestion threshold must be positive")
        self.language = language
        self.routine_cooldown_s = routine_cooldown_s
        self.congestion_threshold_vehicles = congestion_threshold_vehicles
        self.congestion_sustain_s = congestion_sustain_s
        self._history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._emitted_ids: set[str] = set()
        self._run_id: str | None = None
        self._active_vehicle_id: str | None = None
        self._green_announced = False
        self._last_routine_time = float("-inf")
        self._high_queue_since: float | None = None
        self._congestion_announced = False
        self._event_states: dict[str, dict[str, Any]] = {}
        self._intersection_numbers: dict[str, int] = {}

    def _reset(self, run_id: str) -> None:
        self._history.clear()
        self._emitted_ids.clear()
        self._run_id = run_id
        self._active_vehicle_id = None
        self._green_announced = False
        self._last_routine_time = float("-inf")
        self._high_queue_since = None
        self._congestion_announced = False
        self._event_states.clear()
        self._intersection_numbers.clear()

    def _register_intersections(self, snapshot: dict[str, Any]) -> None:
        """Name London controllers from the complete snapshot, not arrival order.

        Every normal SUMO snapshot lists all controllers before any emergency is
        present. Sorting that inventory keeps numbers identical across demand and
        control modes on the same network. Unexpected later IDs append without
        changing names already used by an alert. Raw IDs remain in metadata.
        """
        configuration = snapshot.get("active_configuration") or {}
        london = configuration.get("network") == "london" or str(
            snapshot.get("scenario_selection_id", "")
        ).startswith("london")
        controllers = snapshot.get("traffic_light_controllers") or {}
        identifiers = set(controllers) if isinstance(controllers, dict) else set()
        for event in snapshot.get("emergency_events") or []:
            if isinstance(event, dict) and isinstance(event.get("intersection_id"), str):
                identifiers.add(event["intersection_id"])
        for identifier in sorted(value for value in identifiers if isinstance(value, str)):
            if (london or identifier.startswith("GS_")) and identifier not in self._intersection_numbers:
                self._intersection_numbers[identifier] = len(self._intersection_numbers) + 1

    def _spoken_intersection(self, identifier: object) -> str:
        raw = str(identifier) if identifier is not None else "unknown"
        return str(self._intersection_numbers.get(raw, raw))

    def _emit(
        self,
        message_id: str,
        subject: str,
        now: float,
        *,
        emergency_event: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        assert self._run_id is not None
        text = MESSAGES[message_id][0 if self.language == "en" else 1]
        if emergency_event is not None:
            text = text.format(
                intersection_id=self._spoken_intersection(emergency_event.get("intersection_id"))
            )
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
        if emergency_event is not None:
            alert.update(
                {
                    "emergency_event_id": emergency_event.get("event_id"),
                    "emergency_vehicle_id": emergency_event.get("emergency_vehicle_id"),
                    "intersection_id": emergency_event.get("intersection_id"),
                    "emergency_state": emergency_event.get("state"),
                }
            )
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
        self._register_intersections(snapshot)
        new: list[dict[str, Any]] = []
        def announce(
            message_id: str,
            subject: str,
            emergency_event: dict[str, Any] | None = None,
        ) -> None:
            alert = self._emit(
                message_id, subject, now, emergency_event=emergency_event
            )
            if alert is not None:
                new.append(alert)

        emergency_events = snapshot.get("emergency_events")
        if isinstance(emergency_events, list):
            current_ids: set[str] = set()
            for event in emergency_events:
                if not isinstance(event, dict) or not isinstance(event.get("event_id"), str):
                    continue
                event_id = event["event_id"]
                current_ids.add(event_id)
                previous = self._event_states.get(event_id)
                if previous is None:
                    announce("emergency.detected", event_id, event)
                if (
                    event.get("state") == "priority_active"
                    and (previous is None or previous.get("state") != "priority_active")
                ):
                    announce("emergency.priority_activated", event_id, event)
                if (
                    event.get("state") == "completed"
                    and previous is not None
                    and previous.get("state") == "priority_active"
                ):
                    announce("emergency.priority_completed", event_id, event)
                self._event_states[event_id] = event.copy()
            for event_id in set(self._event_states) - current_ids:
                previous = self._event_states.pop(event_id)
                if previous.get("state") == "priority_active":
                    completed = {**previous, "state": "completed"}
                    announce("emergency.priority_completed", event_id, completed)

        emergency = snapshot.get("emergency_priority") or {}
        vehicle_id = emergency.get("active_vehicle_id")
        approach = emergency.get("active_approach")
        green = self._confirmed_green(snapshot, approach)
        if not isinstance(emergency_events, list) and vehicle_id != self._active_vehicle_id:
            self._active_vehicle_id = vehicle_id
            self._green_announced = False
            if vehicle_id is not None:
                message = "emergency.already_green" if green else "emergency.requested"
                announce(message, vehicle_id)
                self._green_announced = green
        elif not isinstance(emergency_events, list) and vehicle_id is not None and green and not self._green_announced:
            announce("emergency.green_confirmed", vehicle_id)
            self._green_announced = True

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

    def aggregate(self, event_ids: list[str]) -> dict[str, Any] | None:
        """Build speech only from recent server-emitted alerts, never browser text."""
        if not event_ids or len(event_ids) > 8:
            return None
        alerts = [self.get(event_id) for event_id in event_ids]
        if any(alert is None for alert in alerts):
            return None
        known = [alert for alert in alerts if alert is not None]
        if len({alert["run_id"] for alert in known}) != 1:
            return None
        if len(known) == 1:
            return {"text": known[0]["text"], "run_id": known[0]["run_id"]}
        message_ids = {alert["message_id"] for alert in known}
        intersection_ids = sorted(
            {
                str(alert["intersection_id"])
                for alert in known
                if alert.get("intersection_id")
            },
            key=lambda identifier: (self._intersection_numbers.get(identifier, 0), identifier),
        )
        intersections = [self._spoken_intersection(identifier) for identifier in intersection_ids]
        joined = (" and " if self.language == "en" else " și ").join(intersections)
        if message_ids == {"emergency.detected"} and intersections:
            if len(intersections) == 1:
                text = (
                    f"{len(known)} emergency vehicles detected at intersection {intersections[0]}."
                    if self.language == "en" else
                    f"{len(known)} vehicule de intervenție detectate la intersecția {intersections[0]}."
                )
            else:
                text = (
                    f"Emergency vehicles detected at intersections {joined}."
                    if self.language == "en" else
                    f"Vehicule de intervenție detectate la intersecțiile {joined}."
                )
        elif message_ids == {"emergency.priority_activated"} and intersections:
            text = (
                f"Emergency priority activated at intersections {joined}."
                if self.language == "en" else
                f"Prioritate de urgență activată la intersecțiile {joined}."
            )
        else:
            text = " ".join(dict.fromkeys(alert["text"] for alert in known))
        return {"text": text, "run_id": known[0]["run_id"]}
