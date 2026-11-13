"""Deterministic SUMO runner and normalized TraCI snapshot extraction."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, TextIO
from uuid import uuid4

from backend.controller.adaptive import AdaptiveConfig, AdaptiveState, decide

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO_DIRECTORY = REPOSITORY_ROOT / "scenarios" / "single_intersection"
DEFAULT_CONFIG_PATH = DEFAULT_SCENARIO_DIRECTORY / "demo.sumocfg"
DEFAULT_MAPPING_PATH = DEFAULT_SCENARIO_DIRECTORY / "mappings.json"


def _import_traci() -> ModuleType:
    """Import the TraCI module bundled with SUMO without changing global config."""
    try:
        import traci  # type: ignore[import-not-found]

        return traci
    except ModuleNotFoundError:
        candidates = []
        if sumo_home := os.environ.get("SUMO_HOME"):
            candidates.append(Path(sumo_home) / "tools")
        candidates.extend((Path("/usr/share/sumo/tools"), Path("/usr/local/share/sumo/tools")))

        for tools_path in candidates:
            if (tools_path / "traci" / "__init__.py").is_file():
                sys.path.insert(0, str(tools_path))
                import traci  # type: ignore[import-not-found,no-redef]

                return traci

    raise RuntimeError(
        "TraCI was not found. Install SUMO tools or set SUMO_HOME to the SUMO installation root."
    )


def load_scenario_mapping(path: Path = DEFAULT_MAPPING_PATH) -> dict[str, Any]:
    """Load and minimally validate a scenario's project-to-SUMO mapping."""
    with path.open(encoding="utf-8") as mapping_file:
        mapping = json.load(mapping_file)

    required = {
        "schema_version",
        "scenario_id",
        "intersection_id",
        "sumo_junction_id",
        "sumo_traffic_light_id",
        "controlled_lanes",
        "controlled_links",
        "coordinate_system",
    }
    missing = sorted(required.difference(mapping))
    if missing:
        raise ValueError(f"Mapping {path} is missing required keys: {', '.join(missing)}")
    if not mapping["controlled_lanes"]:
        raise ValueError(f"Mapping {path} has no controlled lanes")
    return mapping


@dataclass(frozen=True)
class RunSummary:
    """Small process-level result used by the CLI and integration tests."""

    final_simulation_time_s: float
    steps: int
    departed_vehicles: int
    arrived_vehicles: int
    collisions: int
    teleports: int
    snapshots_written: int


class SumoRunner:
    """Own one TraCI connection while keeping stepping and extraction separate."""

    def __init__(
        self,
        config_path: Path = DEFAULT_CONFIG_PATH,
        mapping_path: Path = DEFAULT_MAPPING_PATH,
        *,
        sumo_binary: str = "sumo",
        run_id: str = "single-intersection-traci",
        traci_module: ModuleType | None = None,
        control_mode: str = "fixed",
    ) -> None:
        self.config_path = config_path.resolve()
        self.mapping_path = mapping_path.resolve()
        self.mapping = load_scenario_mapping(self.mapping_path)
        self.sumo_binary = sumo_binary
        self.run_id = run_id
        self._traci = traci_module
        self._connection: Any | None = None
        self._label = f"flowgency-{uuid4()}"
        if control_mode not in {"fixed", "adaptive"}:
            raise ValueError("control_mode must be fixed or adaptive")
        if control_mode == "adaptive" and self.mapping["scenario_id"] != "single-intersection-v1":
            raise ValueError("adaptive mode is only configured for single-intersection-v1")
        self.control_mode = control_mode
        self._adaptive_config = AdaptiveConfig()
        self._adaptive_state = AdaptiveState()
        self.last_control_reason: str | None = None

    def configure_control_mode(self, control_mode: str) -> None:
        """Select a mode before starting; reset per-run policy history."""
        if self._connection is not None:
            raise RuntimeError("cannot change control mode while SUMO is running")
        if control_mode not in {"fixed", "adaptive"}:
            raise ValueError("control_mode must be fixed or adaptive")
        if control_mode == "adaptive" and self.mapping["scenario_id"] != "single-intersection-v1":
            raise ValueError("adaptive mode is only configured for single-intersection-v1")
        self.control_mode = control_mode
        self._adaptive_state = AdaptiveState()
        self.last_control_reason = None

    @property
    def connection(self) -> Any:
        if self._connection is None:
            raise RuntimeError("SUMO is not running; call start() first")
        return self._connection

    def start(self) -> None:
        """Launch SUMO and establish this runner's labeled TraCI connection."""
        if self._connection is not None:
            raise RuntimeError("SUMO is already running")
        if not self.config_path.is_file():
            raise FileNotFoundError(f"SUMO configuration not found: {self.config_path}")

        self._traci = self._traci or _import_traci()
        (self.config_path.parent / "output").mkdir(parents=True, exist_ok=True)
        command = [
            self.sumo_binary,
            "-c",
            str(self.config_path),
            "--seed",
            "42",
            "--no-step-log",
            "true",
            "--verbose",
            "false",
            "--quit-on-end",
            "true",
        ]
        with contextlib.redirect_stdout(sys.stderr):
            self._traci.start(command, label=self._label, stdout=sys.stderr)
        self._connection = self._traci.getConnection(self._label)
        if self.control_mode == "adaptive":
            self._apply_adaptive_control()

    def advance(self) -> float:
        """Advance exactly one configured SUMO step and return simulation time."""
        self.connection.simulationStep()
        if self.control_mode == "adaptive":
            self._apply_adaptive_control()
        return float(self.connection.simulation.getTime())

    def _apply_adaptive_control(self) -> None:
        """Only change the remaining duration of a verified current green."""
        snapshot = self.extract_snapshot()
        decision, self._adaptive_state = decide(
            snapshot, self._adaptive_state, self._adaptive_config
        )
        self.last_control_reason = decision.reason
        if decision.remaining_green_s is not None:
            self.connection.trafficlight.setPhaseDuration(
                self.mapping["sumo_traffic_light_id"], decision.remaining_green_s
            )

    def has_pending_vehicles(self) -> bool:
        """Return whether vehicles are active or expected from future demand."""
        return int(self.connection.simulation.getMinExpectedNumber()) > 0

    def extract_snapshot(self) -> dict[str, Any]:
        """Read normalized state without advancing the simulation."""
        connection = self.connection
        traffic_light_id = self.mapping["sumo_traffic_light_id"]
        simulation_time = float(connection.simulation.getTime())
        next_switch = float(connection.trafficlight.getNextSwitch(traffic_light_id))

        queues = {}
        for approach, lane_ids in self.mapping["controlled_lanes"].items():
            queues[approach] = {
                "vehicles": sum(
                    int(connection.lane.getLastStepHaltingNumber(lane_id))
                    for lane_id in lane_ids
                ),
                "measurement": "sumo_halting_number",
            }

        vehicles = []
        for vehicle_id in sorted(connection.vehicle.getIDList()):
            x_m, y_m = connection.vehicle.getPosition(vehicle_id)
            vehicles.append(
                {
                    "vehicle_id": vehicle_id,
                    "vehicle_type": connection.vehicle.getTypeID(vehicle_id),
                    "x_m": float(x_m),
                    "y_m": float(y_m),
                    "angle_deg": float(connection.vehicle.getAngle(vehicle_id)),
                    "speed_mps": float(connection.vehicle.getSpeed(vehicle_id)),
                    "road_id": connection.vehicle.getRoadID(vehicle_id),
                }
            )

        snapshot = {
            "schema_version": "1.0",
            "scenario_id": self.mapping["scenario_id"],
            "run_id": self.run_id,
            "intersection_id": self.mapping["intersection_id"],
            "simulation_time_s": simulation_time,
            "traffic_light_id": traffic_light_id,
            "current_phase_index": int(connection.trafficlight.getPhase(traffic_light_id)),
            "current_phase_id": connection.trafficlight.getPhaseName(traffic_light_id),
            "remaining_phase_duration_s": max(0.0, next_switch - simulation_time),
            "queue_lengths_by_approach": queues,
            "traffic_light_state": connection.trafficlight.getRedYellowGreenState(
                traffic_light_id
            ),
            "coordinate_system": self.mapping["coordinate_system"],
            "vehicles": vehicles,
        }
        if self.control_mode == "adaptive":
            snapshot["control_reason"] = self.last_control_reason
        return snapshot

    def run(
        self,
        *,
        sample_every_s: float = 10.0,
        snapshot_stream: TextIO | None = None,
    ) -> RunSummary:
        """Run until no vehicles remain, optionally writing sampled JSON Lines."""
        if sample_every_s <= 0:
            raise ValueError("sample_every_s must be greater than zero")

        steps = snapshots = departed = arrived = collisions = teleports = 0
        next_sample = sample_every_s
        try:
            self.start()
            while self.has_pending_vehicles():
                simulation_time = self.advance()
                steps += 1
                departed += int(self.connection.simulation.getDepartedNumber())
                arrived += int(self.connection.simulation.getArrivedNumber())
                collisions += int(self.connection.simulation.getCollidingVehiclesNumber())
                teleports += int(self.connection.simulation.getStartingTeleportNumber())

                if snapshot_stream is not None and simulation_time + 1e-9 >= next_sample:
                    json.dump(self.extract_snapshot(), snapshot_stream, separators=(",", ":"))
                    snapshot_stream.write("\n")
                    snapshots += 1
                    while next_sample <= simulation_time + 1e-9:
                        next_sample += sample_every_s

            final_time = float(self.connection.simulation.getTime())
            return RunSummary(
                final_simulation_time_s=final_time,
                steps=steps,
                departed_vehicles=departed,
                arrived_vehicles=arrived,
                collisions=collisions,
                teleports=teleports,
                snapshots_written=snapshots,
            )
        finally:
            self.close()

    def close(self) -> None:
        """Close TraCI and its SUMO child process; safe to call repeatedly."""
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None

    def __enter__(self) -> "SumoRunner":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--mappings", type=Path, default=DEFAULT_MAPPING_PATH)
    parser.add_argument("--sumo-binary", default="sumo")
    parser.add_argument("--run-id", default="single-intersection-traci")
    parser.add_argument("--control-mode", choices=("fixed", "adaptive"), default="fixed")
    parser.add_argument("--sample-every", type=float, default=10.0, metavar="SECONDS")
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--print-snapshots", action="store_true", help="write sampled JSON Lines to stdout"
    )
    output.add_argument("--snapshot-output", type=Path, help="write sampled JSON Lines to a file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    stream: TextIO | None = None
    should_close = False
    try:
        if args.print_snapshots:
            stream = sys.stdout
        elif args.snapshot_output is not None:
            args.snapshot_output.parent.mkdir(parents=True, exist_ok=True)
            stream = args.snapshot_output.open("w", encoding="utf-8")
            should_close = True

        runner = SumoRunner(
            args.config,
            args.mappings,
            sumo_binary=args.sumo_binary,
            run_id=args.run_id,
            control_mode=args.control_mode,
        )
        summary = runner.run(sample_every_s=args.sample_every, snapshot_stream=stream)
        print(json.dumps({"run_summary": summary.__dict__}, sort_keys=True), file=sys.stderr)
        return 0 if summary.collisions == 0 and summary.teleports == 0 else 1
    finally:
        if should_close and stream is not None:
            stream.close()


if __name__ == "__main__":
    raise SystemExit(main())
