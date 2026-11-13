# London Oval / Kennington SUMO scenario

This scenario is one connected, left-hand-traffic SUMO network imported from OpenStreetMap for the selected Oval and Kennington camera area. It is independent of `single_intersection/`. It is a simulation approximation, not a validated copy of TfL signal plans.

## Geographic extent and sources

The requested OSM extraction bounding box is:

```text
west=-0.1225, south=51.4720, east=-0.0980, north=51.4870
```

This surrounds all five verified TfL camera coordinates by roughly 400–600 m and gives traffic room to enter and leave on the A3, A23, Camberwell New Road, Vassall Road, Caldwell Street, and connecting streets. OSM ways and relations may include nodes slightly outside the request bounds; the final geo-referenced SUMO network covers approximately 2.07 km by 2.02 km and uses UTM zone 30.

Camera coordinates, names, and view directions were read from TfL's official Place API on 2026-11-13:

| ID | JamCam | TfL common name | Latitude | Longitude | View |
| --- | --- | --- | ---: | ---: | --- |
| J1 | `JamCams_00001.04503` | Camberwell New Rd/Brixton Rd | 51.4812 | -0.11065 | East - CNR twds Camberwell |
| J2 | `JamCams_00001.04339` | Camberwell New Rd/Vassall Rd | 51.4784 | -0.10381 | SW - Vassall Road |
| J3 | `JamCams_00001.04523` | A23 Brixton Rd/Vassell Rd | 51.4765 | -0.11232 | North (A23 twds Kennington) |
| J4 | `JamCams_00001.04611` | A3 Clapham Rd/Caldwell St | 51.4777 | -0.11667 | South - Clapham Rd |
| J5 | `JamCams_00001.04345` | Kenington Pk Rd/Kennington Oval | 51.4824 | -0.11208 | North - A3 twds Elephant |

The API pattern is `https://api.tfl.gov.uk/Place/{jamcam_id}`. The road source is OpenStreetMap data under ODbL, retrieved with SUMO 1.27.1 `osmGet.py`; its retrieval metadata is embedded in `london_bbox.osm.xml`. Official SUMO import guidance: <https://sumo.dlr.de/docs/Networks/Import/OpenStreetMap.html>.

## Files

- `download_osm.sh`: reproducible road-only Overpass download.
- `import.overpass.xml`: exact generated Overpass query.
- `london_bbox.osm.xml`: filtered OSM source, including attribution and timestamp.
- `generate_network.sh`: reproducible `osmBuild.py`/`netconvert` command.
- `london.netccfg`: generated netconvert configuration with all effective options.
- `london.joined.xml`: record of OSM nodes joined into SUMO junction clusters.
- `london.net.xml`: generated geo-referenced SUMO network.
- `generate_demand.sh`: deterministic `randomTrips.py` demand generation.
- `london.trips.xml`: 75 deterministic source/destination trips.
- `london.rou.xml`: validated routed passenger demand.
- `london.sumocfg`: 1,200-second smoke-test configuration.
- `mapping_candidates.json`: candidate mappings for J1–J5; none are declared fully verified.
- `validate_network.py`: connectivity, left-hand, statistics, and mapping-ID validation.
- `generate_traffic_scenarios.py`: deterministic targeted demand generator for normal, rush-hour, and unbalanced profiles.
- `analyze_traffic_scenario.py`: TraCI coverage, queue, throughput, collision, teleport, and trip metric analyzer.
- `demand/` and `configs/`: checked-in targeted route files and matching SUMO configurations.
- `TRAFFIC_SCENARIOS.md`: profile parameters, measured baseline metrics, coverage, and commands.
- `SIGNAL_SAFETY_AUDIT.md`: initial J3 imported-program and controlled-link audit.
- `output/`: ignored runtime summary and trip output.

## Reproduce

Run from the repository root. Scripts are invoked through Bash because executable-bit behavior may differ on NTFS.

```bash
bash scenarios/london_network/download_osm.sh
bash scenarios/london_network/generate_network.sh
bash scenarios/london_network/generate_demand.sh
PYTHONDONTWRITEBYTECODE=1 python3 scenarios/london_network/validate_network.py
```

The import keeps passenger-accessible edges, uses `--lefthand`, preserves street/original names, applies official geometry/roundabout/junction and signal-guessing heuristics, disables generated turnarounds, and retains only the largest weakly connected component. `--tls.join` is deliberately not used: close signal nodes are not automatically collapsed into one controller. Imported TLS phases are SUMO-generated from OSM topology and must not be treated as real TfL timings.

Demand uses seed `42`, departures every 12 seconds from 0–900 seconds (75 passenger cars), at least 500 m trip distance, and fringe-weighted endpoints. `randomTrips.py --validate` and `duarouter` ensure the checked-in routes are connected; this is synthetic baseline demand, not measured traffic.

The original 75-vehicle baseline is preserved. For controller evaluation, use the three targeted profiles documented in [TRAFFIC_SCENARIOS.md](TRAFFIC_SCENARIOS.md). They use seed `20261113`, explicitly cover all mapped candidate approaches, and keep the exact route files stable between fixed and adaptive runs. The selected first controller candidate and safety limitations are documented in [SIGNAL_SAFETY_AUDIT.md](SIGNAL_SAFETY_AUDIT.md).

## Run and inspect

```bash
mkdir -p scenarios/london_network/output
cd scenarios/london_network
sumo -c london.sumocfg
sumo-gui -c london.sumocfg
netedit -s london.net.xml
```

In SUMO-GUI or NetEdit, enable junction/TLS IDs and inspect candidate coordinates and controllers from `mapping_candidates.json` before using any mapping in control logic.

## Validated network statistics

| Metric | Value |
| --- | ---: |
| Junctions | 558 |
| External edges | 1,218 |
| Internal edges | 2,137 |
| External lanes | 1,439 |
| Internal lanes | 2,349 |
| Traffic-light controllers | 23 |
| Weakly connected road components | 1 |

The network root declares `lefthand="true"` and retains a UTM zone 30 projection so SUMO Cartesian positions can be converted back to WGS84 when necessary.

## JamCam-to-SUMO mapping status

| ID | Status | Candidate junction(s) | Candidate TLS ID(s) |
| --- | --- | --- | --- |
| J1 | High-confidence candidate | `cluster_10218369045_4202836241_6391501625` | `GS_cluster_10218369045_4202836241_6391501625` |
| J2 | Ambiguous: two nearby TLS nodes | `2066046353`, `8413292286` | `GS_2066046353`, `GS_8413292286` |
| J3 | High-confidence candidate | `26546583` | `GS_26546583` |
| J4 | Medium-confidence candidate | `33213216` | `GS_33213216` |
| J5 | Ambiguous: two nearby signal clusters | `cluster_108195_6967968844`, `cluster_8982713135_8982713136` | `GS_cluster_108195_6967968844`, `GS_cluster_8982713135_8982713136` |

These statuses combine verified TfL coordinates with proximity and OSM street names. They do not verify camera coverage, signal ownership, link indices, pedestrian stages, or real timings. Detailed distances and incoming edge candidates are in `mapping_candidates.json`.

## Smoke-test result

SUMO 1.27.1 loaded the network and routes with XML validation enabled and reached simulation time 1,200. All 75 vehicles were inserted and arrived; zero remained running or waiting, with zero collisions, zero teleports, and zero unfinished trips. Generated summary and tripinfo files are ignored.

## Import warnings

No warning blocked network generation, but warnings must be reviewed rather than hidden:

- **Usually harmless for this passenger-only scenario:** unsupported cycleway/bus compound types, discarded railway/platform/proposed types, and incomplete public-transport stops/lines at the bounded extract edge.
- **Boundary-related but worth review:** nine ignored/incomplete turn-restriction relations and missing relation members. Routes validate, but affected boundary turns may not reproduce all OSM restrictions.
- **Concerning for manual inspection:** two lanes reported without an incoming connection, three clusters with intersecting left-turn geometry, three tight connections with reduced speed, 25 sharp-turn warnings, and several junction clusters that SUMO declined to join.
- **Blocking:** none for the deterministic smoke test.

Passing a SUMO run proves syntactic/routing viability only. It does not certify junction geometry, lane discipline, pedestrian safety, signal phasing, camera visibility, or real-world control safety.
