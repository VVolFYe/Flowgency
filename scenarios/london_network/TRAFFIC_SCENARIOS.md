# London traffic demand profiles

These synthetic profiles exercise every incoming edge listed in `mapping_candidates.json`. They are repeatable evaluation inputs, not estimates of real London volumes or JamCam visibility.

## Generation model

`generate_traffic_scenarios.py` uses SUMO's bundled `sumolib` to find a valid local passenger route through each of the 23 unique mapped candidate approaches. Routes extend roughly 100–1,300 m before and after the target where the bounded network permits. Departures are spread over 0–900 seconds with deterministic jitter, seed `20261113`, and a deterministic passenger vehicle type (`sigma=0`, `speedFactor=1`, `speedDev=0`).

| Profile | Vehicles per mapped approach | Total vehicles | Purpose |
| --- | ---: | ---: | --- |
| `normal` | 20 | 460 | Moderate distributed baseline |
| `rush_hour` | 30 | 690 | Higher distributed demand and meaningful queues without persistent network-wide gridlock |
| `unbalanced` | 180 on J3 Vassall/Caldwell, 8 elsewhere | 528 | Strong J3 cross-axis demand against sparse Brixton-road demand |

Routes can naturally cross other mapped approaches, so measured target coverage can exceed the number allocated directly to that target. The same checked-in route files must be reused for fixed-versus-adaptive comparisons.

Two bounded-network exceptions are explicit. `11826101#0` has no passenger predecessor, so its routes start on that approach. `1117613589#0` has no outgoing connection and its routes end there; they reach the J2 candidate approach but do **not** traverse controller `GS_8413292286`. This reinforces that J2 remains ambiguous and unsuitable as the first controller target.

## Measured fixed-time baseline

Measurements use SUMO 1.27.1, 1-second steps, junction collision checking, and the imported fixed-time signal programs. A vehicle is counted for an approach when its complete route contains that edge. Queue values are SUMO halting-vehicle counts sampled each second.

| Profile | Vehicles arrived | Avg wait (s) | Avg time loss (s) | Max target queue (vehicles) | Collisions | Teleports | End time (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Normal | 460 / 460 | 38.109 | 49.280 | 11 (J5) | 0 | 0 | 1,201 |
| Rush hour | 690 / 690 | 115.149 | 132.036 | 24 (J5) | 0 | 4 | 1,688 |
| Unbalanced | 528 / 528 | 59.324 | 77.204 | 25 (J3) | 0 | 0 | 1,291 |

The demonstrated joined-junction collision defect and generated U-turn are corrected in Phase 2.2b. Four repeatable rush-hour J5 blocking teleports remain visible and unresolved; see [COLLISION_TELEPORT_AUDIT.md](COLLISION_TELEPORT_AUDIT.md). An earlier rejected rush-hour trial at 70 vehicles per approach produced 171 teleports and 1,278.450 seconds average waiting; it was reduced first to 40 (27 teleports), then to 30 for a useful hackathon comparison.

## Target coverage and queues

The table gives vehicles whose routes contain any mapped incoming approach and the maximum simultaneous halting queue summed over that target's mapped approaches.

| Target | Normal coverage / max queue | Rush coverage / max queue | Unbalanced coverage / max queue | Interpretation |
| --- | ---: | ---: | ---: | --- |
| J1 | 240 / 9 | 360 / 13 | 96 / 4 | High-confidence mapping; useful secondary target |
| J2 | 100 / 4 | 150 / 6 | 40 / 3 | Two candidate TLS; one dead-end mapped edge |
| J3 | 80 / 4 | 120 / 6 | 376 / 25 | Best first target; deliberate asymmetric stress |
| J4 | 100 / 3 | 150 / 6 | 212 / 3 | Candidate mapping only; routes overlap J3 corridor |
| J5 | 240 / 11 | 360 / 24 | 96 / 7 | Two candidate clusters; high network sensitivity |

Per-approach counts and queue maxima are written to ignored `output/<profile>/metrics.generated.json` by the analyzer. Zero queue does not mean zero route coverage; for example, sparse vehicles may pass during green. It also must not be interpreted as an unobserved camera approach becoming zero demand.

## Commands

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scenarios/london_network/generate_traffic_scenarios.py
PYTHONDONTWRITEBYTECODE=1 python3 scenarios/london_network/analyze_traffic_scenario.py normal
PYTHONDONTWRITEBYTECODE=1 python3 scenarios/london_network/analyze_traffic_scenario.py rush_hour
PYTHONDONTWRITEBYTECODE=1 python3 scenarios/london_network/analyze_traffic_scenario.py unbalanced
```

Run SUMO directly:

```bash
sumo -c scenarios/london_network/configs/normal.sumocfg
sumo -c scenarios/london_network/configs/rush_hour.sumocfg
sumo -c scenarios/london_network/configs/unbalanced.sumocfg
sumo-gui -c scenarios/london_network/configs/unbalanced.sumocfg
```

Runtime output belongs under ignored `scenarios/london_network/output/`.
