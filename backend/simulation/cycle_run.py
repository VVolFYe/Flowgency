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
    args = parser.parse_args()
    if args.step_delay_ms < 0:
        parser.error("--step-delay-ms must be nonnegative")
    config = args.config.resolve()
    if not config.is_file():
        parser.error(f"SUMO config not found: {config}")
    if args.adaptive_manifest is not None and not args.adaptive_manifest.is_file():
        parser.error(f"adaptive manifest not found: {args.adaptive_manifest}")
    traci = _import_traci()
    label = f"flowgency-cycle-{uuid4()}"
    with contextlib.redirect_stdout(sys.stderr):
        traci.start([args.sumo_binary, "-c", str(config), "--no-step-log", "true"], label=label, stdout=sys.stderr)
    connection = traci.getConnection(label)
    try:
        signals = load_adaptive_signals(args.adaptive_manifest, connection) if args.adaptive_manifest else []
        decisions = steps = departed = arrived = collisions = teleports = 0
        observed_phases: dict[str, int] = {}
        for signal in signals:
            signal.tick()  # align control with a phase boundary at simulation time zero
            observed_phases[signal.tls_id] = int(connection.trafficlight.getPhase(signal.tls_id))
        while connection.simulation.getMinExpectedNumber() > 0:
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
                    print(json.dumps({"simulation_time_s": connection.simulation.getTime(), **event}), file=sys.stderr)
            simulation = connection.simulation
            departed += int(simulation.getDepartedNumber())
            arrived += int(simulation.getArrivedNumber())
            collisions += int(simulation.getCollidingVehiclesNumber())
            teleports += int(simulation.getStartingTeleportNumber())
        print(json.dumps({"mode": "adaptive" if signals else "fixed", "steps": steps,
                          "departed": departed, "arrived": arrived, "collisions": collisions,
                          "teleports": teleports, "cycle_decisions": decisions}, sort_keys=True))
        return 0 if collisions == 0 and teleports == 0 and departed == arrived else 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
