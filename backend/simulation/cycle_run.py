"""Run any SUMO scenario with validated, configured adaptive signal groups."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

from .cycle_adapter import load_adaptive_signals
from .runner import _import_traci


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="SUMO .sumocfg")
    parser.add_argument("--adaptive-manifest", type=Path, help="verified TLS/phase mapping JSON")
    parser.add_argument("--sumo-binary", default="sumo")
    parser.add_argument("--trace-phases", action="store_true", help="print every observed TLS phase transition")
    parser.add_argument("--step-delay-ms", type=float, default=0.0,
                        help="wall-clock delay after each simulation step, useful with sumo-gui")
    parser.add_argument("--output-directory", type=Path,
                        help="override generated tripinfo and summary output directory")
    parser.add_argument("--max-steps", type=int, default=5000,
                        help="hard simulation-step cap for bounded benchmark runs")
    args = parser.parse_args()
    if args.step_delay_ms < 0:
        parser.error("--step-delay-ms must be nonnegative")
    if args.max_steps <= 0:
        parser.error("--max-steps must be positive")
    config = args.config.resolve()
    if not config.is_file():
        parser.error(f"SUMO config not found: {config}")
    if args.adaptive_manifest is not None and not args.adaptive_manifest.is_file():
        parser.error(f"adaptive manifest not found: {args.adaptive_manifest}")
    traci = _import_traci()
    label = f"flowgency-cycle-{uuid4()}"
    command = [args.sumo_binary, "-c", str(config), "--no-step-log", "true"]
    if args.output_directory is not None:
        output = args.output_directory.resolve()
        output.mkdir(parents=True, exist_ok=True)
        command.extend(["--tripinfo-output", str(output / "tripinfo.xml"),
                        "--summary-output", str(output / "summary.xml")])
    with contextlib.redirect_stdout(sys.stderr):
        traci.start(command, label=label, stdout=sys.stderr)
    connection = traci.getConnection(label)
    try:
        signals = load_adaptive_signals(args.adaptive_manifest, connection) if args.adaptive_manifest else []
        decisions = steps = departed = arrived = collisions = teleports = 0
        decision_events: list[dict[str, object]] = []
        departed_vehicle_ids: list[str] = []
        arrived_vehicle_ids: list[str] = []
        observed_phases: dict[str, int] = {}
        for signal in signals:
            signal.tick()  # align control with a phase boundary at simulation time zero
            observed_phases[signal.tls_id] = int(connection.trafficlight.getPhase(signal.tls_id))
        while connection.simulation.getMinExpectedNumber() > 0 and steps < args.max_steps:
            connection.simulationStep()
            steps += 1
            if args.step_delay_ms:
                time.sleep(args.step_delay_ms / 1000.0)
            for signal in signals:
                current_phase = int(connection.trafficlight.getPhase(signal.tls_id))
                if args.trace_phases and current_phase != observed_phases[signal.tls_id]:
                    print(json.dumps({"simulation_time_s": connection.simulation.getTime(),
                                      "traffic_light_id": signal.tls_id, "phase_index": current_phase,
                                      "event": "phase_entered"}), file=sys.stderr)
                observed_phases[signal.tls_id] = current_phase
                event = signal.tick()
                if event is not None:
                    decisions += 1
                    event_record = {
                        "simulation_time_s": float(connection.simulation.getTime()),
                        **event,
                    }
                    decision_events.append(event_record)
                    print(json.dumps(event_record), file=sys.stderr)
            simulation = connection.simulation
            departed_vehicle_ids.extend(simulation.getDepartedIDList())
            arrived_vehicle_ids.extend(simulation.getArrivedIDList())
            departed += int(simulation.getDepartedNumber())
            arrived += int(simulation.getArrivedNumber())
            collisions += int(simulation.getCollidingVehiclesNumber())
            teleports += int(simulation.getStartingTeleportNumber())
        terminated_by_step_limit = (
            steps >= args.max_steps and connection.simulation.getMinExpectedNumber() > 0
        )
        print(json.dumps({
            "mode": "adaptive" if signals else "fixed",
            "steps": steps,
            "max_steps": args.max_steps,
            "terminated_by_step_limit": terminated_by_step_limit,
            "departed": departed,
            "arrived": arrived,
            "departed_vehicle_ids": departed_vehicle_ids,
            "arrived_vehicle_ids": arrived_vehicle_ids,
            "collisions": collisions,
            "teleports": teleports,
            "cycle_decisions": decisions,
            "cycle_decision_events": decision_events,
        }, sort_keys=True))
        return 0 if not terminated_by_step_limit and collisions == 0 and teleports == 0 and departed == arrived else 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
