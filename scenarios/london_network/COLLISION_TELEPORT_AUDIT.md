# Collision and teleport root-cause audit

This audit uses SUMO 1.27.1 collision XML, warning logs, the generated network, and the unchanged profile volumes. Collision and teleport diagnostics remain enabled.

## Reproduced rush-hour incidents

The four original collisions occurred at 268, 358, 830, and 892 seconds on internal lane `:cluster_105952131_3654005559_10_0`, at approximately SUMO `(887.32, 1648.61)`. In every event, a vehicle traveling straight from `-1113402666#1` to `-1113402667` struck a stopped vehicle turning from `1113402667` to `-1107771062` (Stannary Street) through internal connection `:cluster_105952131_3654005559_3_0`. This is a physical shape-overlap junction collision (`gap=-1`), not a same-lane minimum-gap warning and not a TLS conflict; the junction is type `priority` and has no traffic-light program.

The import had joined OSM nodes `105952131` and `3654005559`, about 16 m apart, into `cluster_105952131_3654005559`. That merge collapsed the intervening Kennington Road segment and placed the minor turning continuation across the major straight movement inside one enlarged priority junction. The minor vehicle stopped within the conflict area while the major movement retained priority. Excluding node `105952131` from automatic junction joining restores two junctions and edge `-1113402666#0` between them.

The two original rush-hour teleports were:

| Time | Vehicle | Lane | Reason | Movement |
| ---: | --- | --- | --- | --- |
| 770 | `rush_hour.J1.02.0007` | `744514111#0_1` | `jam` | Brixton Road to `-744514100#1` |
| 788 | `rush_hour.J5.18.0011` | `744514103#0_1` | `yield` | Kennington Park Road to `-744514100#1` |

Both are at J5 candidate TLS `GS_cluster_108195_6967968844`, where links 0–1 and 2–3 alternate in 42-second green / 3-second yellow groups. Both approaches feed the same short downstream Kennington Park Road edge. SUMO teleported each vehicle after the default 300-second waiting threshold. The evidence supports downstream congestion/priority blocking, not incompatible simultaneous green: links 0–1 use `GGrrGGG`, while links 2–3 use `rrGGrrr`. Because J5 maps to two ambiguous nearby controllers and real timings are unverified, no signal or right-of-way change is justified automatically.

## Corrections and validation

- `generate_network.sh` now excludes OSM node `105952131` from automatic junction joining. A candidate rebuild with route repair produced zero collisions in normal, rush-hour, and unbalanced runs while preserving the original two rush-hour teleports.
- Generated route selection now rejects explicit SUMO `dir="T"` connections. The former unbalanced teleport used the generated U-turn `-1306644990#2 -> 1119391144#0` at junction `33228800`; that modeling artifact is removed without reducing demand.
- The corrected network has 559 junctions, 1,220 external edges, 1,443 external lanes, 23 TLS controllers, one weak component, and remains left-hand. All J1–J5 mapping IDs validate.

After regenerating deterministic demand with the same counts and seed, measured results were: normal 460/460 arrivals, zero collisions, zero teleports; rush hour 690/690 arrivals, zero collisions, four J5 teleports; unbalanced 528/528 arrivals, zero collisions, zero teleports. The extra pair of rush-hour J5 teleports shows that the bottleneck is sensitive to deterministic route interactions. A broader experiment that routed around other mapped approaches eliminated these teleports but materially reduced congestion, so it was rejected rather than used to make logs appear clean.

## Remaining action

Inspect J5 in SUMO-GUI/NetEdit around 740–800 seconds, including downstream lane occupancy and the neighboring controller, before changing topology or timings. Keep the current teleports visible in comparisons. Do not alter signal clearance, collision sensitivity, demand volume, or teleport thresholds without additional evidence.
