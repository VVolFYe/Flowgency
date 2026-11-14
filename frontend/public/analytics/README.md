# Static analytics files

Committed JSON files behind the Statistics page (`/operator/statistics`,
`/analyst/statistics`). They are the source of truth. The page reads them
through the backend API (`GET /api/analytics`, `GET /api/analytics/{id}`),
which serves a local SQLite copy (`data/analytics.sqlite3`, gitignored). File
formats, the table, and the endpoints are defined in `docs/DATA_CONTRACTS.md`
section K. `null` always means unknown; it is never a stand-in for zero.

## Workflow: generate JSON → commit → run the loader

1. Generate or refresh a JSON file with its exporter (commands below). The
   exporter also registers the file in `index.json`.
2. Commit the JSON files and `index.json`.
3. Load them into the local database, from the repository root:

   ```bash
   python3 -m backend.analytics.load            # optional: --db PATH --index PATH
   ```

   The loader is idempotent (one upserted row per index entry), so rerun it
   after every change or after pulling new JSON. Until it has run, the
   Statistics page shows a 503 message asking for it. The database path can be
   changed with `FLOWGENCY_ANALYTICS_DB` (relative to the repository root).
   Rows for entries removed from `index.json` are not deleted; delete
   `data/analytics.sqlite3` and reload to drop them.

| File | Kind | Producer |
| --- | --- | --- |
| `index.json` | index | both exporters (`--analytics-index` / `--index`) upsert their entry |
| `youtube.json` | vision | `backend/vision/export_analytics.py` |
| `<scenario>.json` | simulation | `backend/simulation/compare_cycles.py --analytics-out` |

An exporter registers its file in `index.json` only after it writes it, so the
index never points at a missing file. The benchmark snapshots in
`../benchmarks/` are separate and are not changed by these exporters.

## Vision: `youtube.json`

From the committed gate-mode sample (`backend/vision/samples/youtube_full/`).
No CV stack, no video, and no SUMO are needed:

```bash
python3 -m backend.vision.export_analytics \
  --counts backend/vision/samples/youtube_full/counts.jsonl \
  --events backend/vision/samples/youtube_full/events.jsonl \
  --out frontend/public/analytics/youtube.json \
  --label "YouTube top-down intersection" \
  --index frontend/public/analytics/index.json
```

## Simulation: fixed vs adaptive

Each command runs both modes through `cycle_run` with the same config, seed
and routes, writes the usual `comparison_report.json` under an ignored
`scenarios/**/output/` directory, and also writes the analytics file. It needs
Eclipse SUMO: `sumo` on `PATH` and TraCI importable (set `SUMO_HOME` or
install the SUMO tools). Run from the repository root with the backend
virtual environment active. Inputs match the `provenance` blocks in
`../benchmarks/`. Rush hour uses the same manifest as London normal.

Validation failures (for example teleports) are still exported, with
`validation.passed = false` and all errors. In that case the command exits
with status 1.

```bash
OUT=frontend/public/analytics

python3 -m backend.simulation.compare_cycles \
  --config scenarios/london_network/configs/normal.sumocfg \
  --adaptive-manifest scenarios/london_network/network_adaptive.experimental.json \
  --output-directory scenarios/london_network/output/analytics_london_normal \
  --scenario-id london_normal --scenario-name "London — Normal Traffic" \
  --adaptive-label "Network adaptive" \
  --analytics-out $OUT/london_normal.json --analytics-index $OUT/index.json

python3 -m backend.simulation.compare_cycles \
  --config scenarios/london_network/configs/rush_hour.sumocfg \
  --adaptive-manifest scenarios/london_network/network_adaptive.experimental.json \
  --output-directory scenarios/london_network/output/analytics_london_rush_hour \
  --scenario-id london_rush_hour --scenario-name "London — Rush Hour" \
  --adaptive-label "Network adaptive" \
  --analytics-limitation "Rush hour has known teleports at the J5 candidate controller (see scenarios/london_network/COLLISION_TELEPORT_AUDIT.md); the run is exported as-is and flagged." \
  --analytics-out $OUT/london_rush_hour.json --analytics-index $OUT/index.json

python3 -m backend.simulation.compare_cycles \
  --config scenarios/london_network/configs/unbalanced.sumocfg \
  --adaptive-manifest scenarios/london_network/network_adaptive.experimental.json \
  --output-directory scenarios/london_network/output/analytics_london_unbalanced_network \
  --scenario-id london_unbalanced_network \
  --scenario-name "London — Unbalanced Traffic (network adaptive)" \
  --adaptive-label "Network adaptive" \
  --analytics-out $OUT/london_unbalanced_network.json --analytics-index $OUT/index.json

python3 -m backend.simulation.compare_cycles \
  --config scenarios/london_network/configs/unbalanced.sumocfg \
  --adaptive-manifest scenarios/london_network/j3_adaptive.experimental.json \
  --output-directory scenarios/london_network/output/analytics_london_unbalanced_j3 \
  --scenario-id london_unbalanced_j3 \
  --scenario-name "London — Unbalanced Traffic (historical J3-only)" \
  --adaptive-label "Adaptive J3" \
  --analytics-limitation "Historical J3-only manifest: every other London controller stays on fixed timing." \
  --analytics-out $OUT/london_unbalanced_j3.json --analytics-index $OUT/index.json
```

Keep each file under about 200 KB. Time series are downsampled automatically
when a run would exceed 600 samples per mode.

### Synthetic: blocked

`synthetic.json` cannot be produced with `compare_cycles` yet. The synthetic
benchmark used `backend/controller/adaptive.py` through `SumoRunner`
(`backend/simulation/compare.py`), not a `cycle_run` manifest.
`scenarios/single_intersection/demo.rou.xml` also defines demand as `<flow>`s,
which `compare_cycles.read_expected_vehicle_ids` rejects ("benchmark demand
must use explicit vehicle IDs, not flows"). This needs a decision from the
simulation owner before an export is added.
