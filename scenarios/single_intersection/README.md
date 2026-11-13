# Synthetic single-intersection scenario

This deterministic baseline contains one artificial four-approach signalized junction (`demo_01`). It is not mapped to London or any JamCam. Each approach has one 50 km/h lane and supports only a straight movement. The network is generated for left-hand traffic; with one lane and no turns, lane-side behavior is intentionally minimal but the network metadata and generation mode establish the correct convention for later scenarios.

## Files

- `demo.nod.xml`, `demo.edg.xml`, `demo.con.xml`: reproducible network sources.
- `demo.tll.xml`: fixed traffic-light program used by `netconvert`.
- `demo.net.xml`: generated SUMO network, committed so the scenario runs immediately.
- `demo.rou.xml`: four deterministic straight-through flows.
- `demo.sumocfg`: 420-second simulation, seed, and output configuration.
- `mappings.json`: verified project-to-SUMO junction, edge, lane, and signal-link mapping.
- `output/`: generated trip and summary output; ignored by Git.

## Regenerate the network

Run from this directory:

```bash
netconvert \
  --node-files demo.nod.xml \
  --edge-files demo.edg.xml \
  --connection-files demo.con.xml \
  --tllogic-files demo.tll.xml \
  --lefthand true \
  --no-turnarounds true \
  --output-file demo.net.xml
```

`netconvert` 1.27.1 generated the checked-in network. Regeneration with another SUMO release may produce harmless serialization differences; validate before accepting them.

## Run headlessly

```bash
mkdir -p output
sumo -c demo.sumocfg
```

The simulation uses seed `42`, one-second steps, and runs from 0 through 420 seconds. Each direction emits one vehicle every 10 seconds for 300 seconds, with 2-second offsets between directions: 120 vehicles total.

## View in SUMO GUI

```bash
mkdir -p output
sumo-gui -c demo.sumocfg
```

## Fixed-time signal program

The 70-second cycle has north/south green for 30 seconds, 3 seconds yellow, 2 seconds all-red, east/west green for 30 seconds, 3 seconds yellow, and 2 seconds all-red. Generated signal positions are `0=south`, `1=east`, `2=north`, and `3=west`, so north/south use `GrGr` and east/west use `rGrG`. Conflicting axes are never green or yellow simultaneously. This simplified scenario has no pedestrian phases; later scenarios must model and preserve them explicitly.

Generated output is `output/tripinfo.xml` and `output/summary.xml`. Trip info includes unfinished vehicles, although a successful baseline run should finish all trips before the configured end.

## Run through the Python TraCI runner

From the repository root, run to completion without emitting snapshots:

```bash
python3 -m backend.simulation.runner
```

Print one compact JSON snapshot every 10 simulated seconds to stdout:

```bash
python3 -m backend.simulation.runner --sample-every 10 --print-snapshots
```

Write snapshots to the scenario's ignored output directory:

```bash
python3 -m backend.simulation.runner \
  --sample-every 10 \
  --snapshot-output scenarios/single_intersection/output/snapshots.jsonl
```

The runner locates bundled TraCI via `SUMO_HOME/tools` or standard Linux SUMO paths, so this installation needs no Python package or virtual environment. It stops after all scheduled vehicles arrive, closes its labeled TraCI connection in a `finally` block, and reports run totals to stderr. Its `advance()` and `extract_snapshot()` methods are independent for later API orchestration.
