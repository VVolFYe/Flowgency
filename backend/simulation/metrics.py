"""Run-level metrics accumulated once per authoritative SUMO step."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class RunMetrics:
    """Accumulate metrics that must survive individual vehicle arrival."""

    total_waiting_time_s: float = 0.0
    departed_vehicle_count: int = 0
    arrived_vehicle_count: int = 0
    maximum_network_queue_vehicles: int = 0

    def record_step(
        self,
        connection: Any,
        *,
        step_duration_s: float,
        vehicle_ids: Iterable[str],
        network_queue_vehicles: int,
    ) -> None:
        """Record exactly one completed simulation interval.

        SUMO's per-vehicle waiting time is positive only while the vehicle is
        in a traffic-induced halt and excludes intentional ``<stop>`` stages.
        Counting each such vehicle once per step avoids summing the API's
        consecutive waiting counter repeatedly.
        """
        if step_duration_s < 0:
            raise ValueError("simulation step duration must be nonnegative")
        ids = tuple(vehicle_ids)
        waiting_vehicles = sum(
            float(connection.vehicle.getWaitingTime(vehicle_id)) > 0.0
            for vehicle_id in ids
        )
        self.total_waiting_time_s += waiting_vehicles * step_duration_s
        self.departed_vehicle_count += int(connection.simulation.getDepartedNumber())
        self.arrived_vehicle_count += int(connection.simulation.getArrivedNumber())
        self.maximum_network_queue_vehicles = max(
            self.maximum_network_queue_vehicles, int(network_queue_vehicles)
        )

    def snapshot(
        self,
        *,
        active_vehicle_count: int,
        network_queue_vehicles: int,
    ) -> dict[str, Any]:
        average = (
            self.total_waiting_time_s / self.departed_vehicle_count
            if self.departed_vehicle_count
            else None
        )
        return {
            "total_waiting_time_s": self.total_waiting_time_s,
            "average_waiting_time_s": average,
            "average_waiting_time_denominator": "departed_vehicle_count",
            "departed_vehicle_count": self.departed_vehicle_count,
            "arrived_vehicle_count": self.arrived_vehicle_count,
            "active_vehicle_count": int(active_vehicle_count),
            "network_queue_vehicles": int(network_queue_vehicles),
            "maximum_network_queue_vehicles": self.maximum_network_queue_vehicles,
            "total_time_loss_s": None,
            "average_time_loss_s": None,
            "time_loss_status": "deferred_to_completed_tripinfo",
            "waiting_time_measurement": "sum_waiting_vehicle_intervals_x_step_duration",
        }
