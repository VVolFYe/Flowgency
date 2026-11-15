"""Streaming, versioned replay export for normalized SUMO snapshots."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, TextIO


REPLAY_SCHEMA_VERSION = "1.0"


def _finite_number(value: object, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise ValueError(f"replay {field} must be a finite number")
    return float(value)


def snapshot_to_replay_frame(snapshot: dict[str, Any], frame_index: int) -> dict[str, Any]:
    """Select deterministic dynamic fields without inventing simulation state."""
    timestamp = _finite_number(snapshot.get("simulation_time_s"), "simulation_time_s")
    vehicles = []
    for source in sorted(snapshot.get("vehicles", []), key=lambda item: item["vehicle_id"]):
        vehicles.append({
            "vehicle_id": str(source["vehicle_id"]),
            "x_m": _finite_number(source.get("x_m"), "vehicle.x_m"),
            "y_m": _finite_number(source.get("y_m"), "vehicle.y_m"),
            "angle_deg": _finite_number(source.get("angle_deg"), "vehicle.angle_deg"),
            "speed_mps": _finite_number(source.get("speed_mps"), "vehicle.speed_mps"),
            "lane_id": str(source.get("lane_id", "")),
            "edge_id": str(source.get("road_id", "")),
        })
    controllers = snapshot.get("traffic_light_controllers", {})
    traffic_lights = [
        {
            "traffic_light_id": str(traffic_light_id),
            "phase_index": int(controller["current_phase_index"]),
            "phase_id": str(controller.get("current_phase_id", "")),
            "state": str(controller["traffic_light_state"]),
        }
        for traffic_light_id, controller in sorted(controllers.items())
    ]
    frame = {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "record_type": "frame",
        "frame_index": frame_index,
        "simulation_time_s": timestamp,
        "coordinate_system": str(snapshot.get("coordinate_system", "")),
        "vehicles": vehicles,
        "traffic_lights": traffic_lights,
    }
    metrics = snapshot.get("metrics")
    if isinstance(metrics, dict):
        total_waiting = _finite_number(
            metrics.get("total_waiting_time_s"), "metrics.total_waiting_time_s"
        )
        if total_waiting < 0:
            raise ValueError("replay cumulative waiting time must be nonnegative")
        counts = {}
        for field in ("active_vehicle_count", "arrived_vehicle_count"):
            value = metrics.get(field)
            if type(value) is not int or value < 0:
                raise ValueError(f"replay metrics.{field} must be a nonnegative integer")
            counts[field] = value
        frame["metrics"] = {
            "cumulative_waiting_time_s": total_waiting,
            **counts,
            "measurement": "sum_waiting_vehicle_intervals_x_step_duration",
        }
    return frame


class ReplayWriter:
    """Write one normalized snapshot per line and retain only summary metadata."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        if self.path.exists():
            raise FileExistsError(f"refusing to overwrite replay output: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream: TextIO = self.path.open("x", encoding="utf-8", newline="\n")
        self.frame_count = 0
        self.first_simulation_time_s: float | None = None
        self.last_simulation_time_s: float | None = None
        self.vehicle_ids: set[str] = set()
        self.final_cumulative_waiting_time_s: float | None = None
        self.closed = False

    def write_snapshot(self, snapshot: dict[str, Any]) -> None:
        if self.closed:
            raise RuntimeError("replay writer is closed")
        frame = snapshot_to_replay_frame(snapshot, self.frame_count)
        timestamp = float(frame["simulation_time_s"])
        if self.last_simulation_time_s is not None and timestamp <= self.last_simulation_time_s:
            raise ValueError("replay timestamps must increase strictly")
        self._stream.write(json.dumps(frame, sort_keys=True, separators=(",", ":")) + "\n")
        self.first_simulation_time_s = (
            timestamp if self.first_simulation_time_s is None else self.first_simulation_time_s
        )
        self.last_simulation_time_s = timestamp
        self.vehicle_ids.update(vehicle["vehicle_id"] for vehicle in frame["vehicles"])
        metrics = frame.get("metrics")
        if metrics is not None:
            waiting = float(metrics["cumulative_waiting_time_s"])
            if (
                self.final_cumulative_waiting_time_s is not None
                and waiting < self.final_cumulative_waiting_time_s
            ):
                raise ValueError("replay cumulative waiting time must not decrease")
            self.final_cumulative_waiting_time_s = waiting
        self.frame_count += 1

    def close(self) -> None:
        if not self.closed:
            self._stream.close()
            self.closed = True

    def summary(self) -> dict[str, Any]:
        if not self.closed:
            raise RuntimeError("close replay writer before requesting its summary")
        digest = hashlib.sha256()
        with self.path.open("rb") as replay_file:
            for chunk in iter(lambda: replay_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return {
            "schema_version": REPLAY_SCHEMA_VERSION,
            "format": "jsonl",
            "path": str(self.path),
            "sha256": digest.hexdigest(),
            "size_bytes": self.path.stat().st_size,
            "frame_count": self.frame_count,
            "first_simulation_time_s": self.first_simulation_time_s,
            "last_simulation_time_s": self.last_simulation_time_s,
            "observed_vehicle_count": len(self.vehicle_ids),
            "waiting_series_available": self.final_cumulative_waiting_time_s is not None,
            "final_cumulative_waiting_time_s": self.final_cumulative_waiting_time_s,
        }

    def __enter__(self) -> "ReplayWriter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def inspect_replay(path: Path) -> dict[str, Any]:
    """Validate a completed JSONL replay without loading it into memory."""
    frame_count = 0
    first_time: float | None = None
    last_time: float | None = None
    vehicle_ids: set[str] = set()
    traffic_light_ids: set[str] = set()
    coordinate_system: str | None = None
    waiting_samples = 0
    previous_waiting: float | None = None
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            try:
                frame = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid replay JSON on line {line_number}") from exc
            if frame.get("schema_version") != REPLAY_SCHEMA_VERSION or frame.get("record_type") != "frame":
                raise ValueError(f"invalid replay schema on line {line_number}")
            if frame.get("frame_index") != frame_count:
                raise ValueError("replay frame indices are not contiguous")
            timestamp = _finite_number(frame.get("simulation_time_s"), "simulation_time_s")
            if last_time is not None and timestamp <= last_time:
                raise ValueError("replay timestamps are not strictly increasing")
            if first_time is None:
                first_time = timestamp
            current_coordinate_system = str(frame.get("coordinate_system", ""))
            if not current_coordinate_system or (
                coordinate_system is not None and current_coordinate_system != coordinate_system
            ):
                raise ValueError("replay coordinate system is missing or inconsistent")
            coordinate_system = current_coordinate_system
            for vehicle in frame.get("vehicles", []):
                vehicle_ids.add(str(vehicle["vehicle_id"]))
                for field in ("x_m", "y_m", "angle_deg", "speed_mps"):
                    _finite_number(vehicle.get(field), f"vehicle.{field}")
            for light in frame.get("traffic_lights", []):
                traffic_light_ids.add(str(light["traffic_light_id"]))
                if not isinstance(light.get("state"), str) or type(light.get("phase_index")) is not int:
                    raise ValueError("replay traffic-light state is invalid")
            metrics = frame.get("metrics")
            if metrics is not None:
                if not isinstance(metrics, dict):
                    raise ValueError("replay metrics must be an object")
                waiting = _finite_number(
                    metrics.get("cumulative_waiting_time_s"),
                    "metrics.cumulative_waiting_time_s",
                )
                if waiting < 0 or (previous_waiting is not None and waiting < previous_waiting):
                    raise ValueError("replay cumulative waiting time is invalid")
                for field in ("active_vehicle_count", "arrived_vehicle_count"):
                    value = metrics.get(field)
                    if type(value) is not int or value < 0:
                        raise ValueError(f"replay metrics.{field} is invalid")
                if metrics.get("measurement") != "sum_waiting_vehicle_intervals_x_step_duration":
                    raise ValueError("replay waiting-time measurement is unsupported")
                if waiting_samples == 0 and waiting != 0:
                    raise ValueError("replay cumulative waiting time must begin at zero")
                previous_waiting = waiting
                waiting_samples += 1
            last_time = timestamp
            frame_count += 1
    if not frame_count:
        raise ValueError("replay contains no frames")
    if waiting_samples not in (0, frame_count):
        raise ValueError("replay waiting-time series is incomplete")
    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "frame_count": frame_count,
        "first_simulation_time_s": first_time,
        "last_simulation_time_s": last_time,
        "coordinate_system": coordinate_system,
        "vehicle_ids": sorted(vehicle_ids),
        "traffic_light_ids": sorted(traffic_light_ids),
        "waiting_series_available": waiting_samples == frame_count,
        "final_cumulative_waiting_time_s": previous_waiting,
    }
