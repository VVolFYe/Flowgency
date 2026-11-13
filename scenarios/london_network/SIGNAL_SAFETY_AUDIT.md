# Initial signal-program safety audit: J3

This is an audit of the imported SUMO model, not certification of a TfL controller or real-world safety. `mapping_candidates.json` marks J3 as a high-confidence candidate based on location and road names; camera field of view and signal ownership remain unverified.

## Selected first target

- Project target: J3, Brixton Rd / Vassall Rd / Caldwell St (`JamCams_00001.04523`)
- SUMO junction: `26546583`
- SUMO TLS: `GS_26546583`
- Selection rationale: one candidate TLS, four named incoming approaches, and an explainable two-green-group program. J1 is also plausible, but J3 directly supports the asymmetric controller experiment. J2 and J5 remain multi-controller ambiguities.

## Imported phase program

The 90-second static program is stored in `london.net.xml` and is unchanged.

| Phase | Duration (s) | State | Interpretation in the model |
| ---: | ---: | --- | --- |
| 0 | 42 | `rrrGGGrrrGGG` | Brixton Road groups (links 3–5 and 9–11) green |
| 1 | 3 | `rrryyyrrryyy` | Brixton Road groups yellow |
| 2 | 42 | `GGgrrrGGgrrr` | Vassall/Caldwell groups (links 0–2 and 6–8) green; lowercase `g` yields |
| 3 | 3 | `yyyrrryyyrrr` | Vassall/Caldwell groups yellow |

There is no explicit all-red phase in this imported SUMO program. Future control must preserve phase order and at least the modeled 3-second yellow transitions. It must not assume that 3 seconds, or no all-red interval, is correct for the real London junction. Any all-red requirement needs TfL/source-plan evidence or an explicit conservative simulation design decision.

## Controlled links

| Link indices | Incoming edge | Road | Modeled movements |
| --- | --- | --- | --- |
| 0–2 | `-1015085160#0` | Vassall Road | left, straight, right |
| 3–5 | `1118018433#0` | Brixton Road | left and two straight lane links |
| 6–8 | `-5001019#4` | Caldwell Street | left, straight, right |
| 9–11 | `-66924592#2` | Brixton Road | left and two straight lane links |

The two green phases separate the modeled Brixton axis from the modeled Vassall/Caldwell axis. SUMO's generated link states provide conflict handling within this topology, including yielding lowercase-green links. No conflicting major approach groups receive uppercase green together in the imported program.

## Pedestrians and clearance

The passenger-focused OSM import contains no controlled pedestrian links or walking-area/crossing stages at this TLS. Therefore pedestrian compatibility and clearance are **not verified**, not absent in the real junction. Adaptive control must not be presented as pedestrian-safe until crossings and their timing requirements are modeled or explicitly validated.

The successful simulation runs verify only that SUMO can execute the modeled phase program. They do not validate intergreen calculations, sight distances, conflict zones, stop-line placement, TfL timings, or real-world safety.

## Warnings and follow-up

- The joined-junction collision defect found outside J1–J5 was corrected in Phase 2.2b; junction collision checking remains enabled. J5 congestion teleports remain unresolved.
- The Phase 2.1 import reported three intersecting-left-turn geometries, tight connections, sharp turns, and disconnected lane connections. These remain manual-review items.
- J3 itself should be inspected in NetEdit/SUMO-GUI with link indices and request/conflict visualization enabled.
- Before implementing adaptive timing, encode phases 1 and 3 as immutable transition phases; adjust only green dwell in phases 0 and 2 within configured bounds.
