# SUMO scenarios

Scenario definitions are source assets and belong in Git. Generated logs, traces, metrics, and run outputs belong in an `output/` directory and are ignored.

```text
scenario_name/
  README.md      purpose, sources, assumptions, and run notes
  *.sumocfg      SUMO run configuration
  *.net.xml      network
  *.rou.xml      routes and demand
  *.add.xml      detectors, signals, or outputs
  mappings.json  project approach/intersection IDs to verified SUMO IDs
```

Keep source/intermediate SUMO files (`*.nod.xml`, `*.edg.xml`, connection/type files) when needed to reproduce the network. Use relative paths. Record SUMO version, coordinates, left-hand assumptions, random seed, demand provenance, signal/pedestrian phases, and outputs. `single_intersection/` is for the first validated scenario. `london_network/` is for the later connected network, not five independent simulators.

## Candidate camera references

| ID | Location | TfL JamCam ID |
| --- | --- | --- |
| J1 | Camberwell New Rd / Brixton Rd (Oval) | `JamCams_00001.04503` |
| J2 | Camberwell New Rd / Vassall Rd | `JamCams_00001.04339` |
| J3 | Brixton Rd / Vassall Rd / Caldwell St | `JamCams_00001.04523` |
| J4 | Clapham Rd / Caldwell St | `JamCams_00001.04611` |
| J5 | Kennington Park Rd / Kennington Oval | `JamCams_00001.04345` |

These identify cameras, not SUMO junctions or traffic lights. Validate metadata, direction, visible approaches, geometry, signals, and SUMO node/edge/lane/traffic-light/link mappings. Camera-occluded approaches require explicit assumptions, never implicit zero flow.
