# AI Traffic datasets

The AI Traffic page (`/operator/ai-traffic`) replays prerecorded SUMO
trajectories next to the recorded video. It never starts a live simulation.
Two allowlisted datasets share the same playback UI:

| Selection ID | Label | Bundle directory | Videos |
| --- | --- | --- | --- |
| `demo1` (default) | Center Street & 500 West Intersection | `assets/ai-traffic/versions/waiting-v1/` | original + AI-annotated |
| `demo2` | Center Street & University Avenue Intersection | `assets/ai-traffic/versions/demo2-v1/` | AI-annotated only |

Each bundle contains `replay_manifest.json`, `videos/*.mp4` (Git LFS),
`replays/fixed.jsonl`, `replays/gap_v1.jsonl` and
`reports/comparison_report.json`. Every number shown on the page comes from
these files. A bundle that has not been generated is reported as unavailable;
the backend never substitutes one dataset's files for another.

## Bundle discovery and overrides

Both bundles are resolved relative to the repository, so a fresh clone works
from any working directory once Git LFS has downloaded the videos. No `.env`
entry is required. Optional backend overrides for custom deployments:

- `FLOWGENCY_REPLAY_ASSET_DIR`: Demo 1 bundle (unchanged behavior).
- `FLOWGENCY_REPLAY_ASSET_DIR_DEMO2`: Demo 2 bundle.

Demo 2 is refused if it points at the Demo 1 directory or if its manifest
`dataset_id` equals Demo 1's.

## Demo 2 inputs and limitations

- AI inputs: `backend/vision/samples/youtube2/counts.jsonl` (156 one-second
  observations) and `events.jsonl` (403 events, 132 `approach_entered`:
  north 49, east 21, south 44, west 18).
- Source video: `assets/ai-traffic/inputs/demo2/annotated_source.mp4`
  (MPEG-4 Part 2, 1280x720, 23.976 fps, 156.03 s). It is ignored by Git; the
  bundle stores a browser H.264 copy.
- Only the AI-annotated video exists. The manifest has no `original_video`
  asset, `video.duration_s` is `null` and `video.source_kind` is
  `annotated_only`. The page disables the Original option.
- The first three count observations (t = 0–2 s) are the vision warm-up and
  contain no arm data (unknown, not zero). Per the data contract, the starting
  offset comes from the first complete line, t = 3 s (16 vehicles on approach),
  and is metadata only. Current code therefore does not need
  `--allow-unknown-initial-observations` for this recording; the flag remains
  valid in the commands below, which match how the committed bundle was
  generated. That bundle was produced before this warm-up rule was merged, so
  its limitation text describes the starting vehicles as unknown at t = 0. The
  route file, replays and metrics do not depend on this metadata.
- Three `approach_left` events (west arm, tracks 41, 10, 550) are validated
  against their `approach_entered` event and do not change demand.

## Generating the Demo 2 bundle

Run from the repository root in a host terminal. Every step refuses to
overwrite existing outputs. Use the same Python environment that runs the
backend; it needs SUMO 1.27.1 with TraCI and FFmpeg/ffprobe.

```bash
cd /home/wolfye/ProiectUnihack26/Flowgency
export SUMO_HOME="${SUMO_HOME:-/usr/share/sumo}"
D2=assets/ai-traffic/versions/demo2-v1
IN=backend/vision/samples/youtube2
test -e "$D2/replay_manifest.json" && echo "STOP: $D2 already has a manifest" || mkdir -p "$D2/replays"
```

1. Fixed replay (expected exit code 0):

```bash
python3 -m backend.simulation.ai_fixed_run \
  --counts "$IN/counts.jsonl" --events "$IN/events.jsonl" \
  --output-directory "$D2/runs/fixed" \
  --replay-output "$D2/replays/fixed.jsonl" \
  --allow-unknown-initial-observations > /dev/null; echo "fixed exit=$?"
```

2. Adaptive gap_v1 replay on the identical demand (expected exit code 0):

```bash
python3 -m backend.simulation.ai_adaptive_run \
  --counts "$IN/counts.jsonl" --events "$IN/events.jsonl" \
  --output-directory "$D2/runs/gap_v1" \
  --adaptive-strategy gap_v1 \
  --fixed-demand-route "$D2/runs/fixed/ai_demand.rou.xml" \
  --replay-output "$D2/replays/gap_v1.jsonl" \
  --allow-unknown-initial-observations > /dev/null; echo "adaptive exit=$?"
```

3. Validated comparison report (prints the summary; must say `VALIDATED`):

```bash
python3 -m backend.simulation.ai_compare \
  --fixed-directory "$D2/runs/fixed" \
  --adaptive-directory "$D2/runs/gap_v1" \
  --output-directory "$D2/reports/comparison-run" \
  --adaptive-strategy gap_v1 --per-vehicle-csv
```

4. and 5. Browser H.264 video and final manifest. The bundle tool transcodes
the MPEG-4 source with
`ffmpeg -nostdin -v warning -i <source> -map 0:v:0 -an -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -movflags +faststart videos/annotated.mp4`,
rejects the result unless it is H.264/yuv420p with the source duration
(±0.1 s), copies the comparison report, records sizes and SHA-256 checksums,
and writes `replay_manifest.json`. No `--original-video` is passed because none
exists.

```bash
python3 -m backend.simulation.ai_replay_bundle \
  --output-directory "$D2" \
  --annotated-video assets/ai-traffic/inputs/demo2/annotated_source.mp4 \
  --fixed-replay "$D2/replays/fixed.jsonl" \
  --gap-replay "$D2/replays/gap_v1.jsonl" \
  --fixed-run-report "$D2/runs/fixed/fixed_run_summary.json" \
  --adaptive-run-report "$D2/runs/gap_v1/adaptive_run_summary.json" \
  --comparison-report "$D2/reports/comparison-run/comparison_report.json" \
  --dataset-id youtube2_intersection_156s_v1 \
  --display-name "Second prerecorded AI-derived traffic experiment" \
  --require-waiting-series
```

6. Validate what the API will serve:

```bash
python3 - <<'EOF'
from backend.api.replay_assets import ReplayDatasetRegistry
registry = ReplayDatasetRegistry()
for item in registry.list_datasets()["datasets"]:
    print(item["dataset_id"], item["available"], item["detail"], item["video_sources"])
m = registry.public_manifest("demo2")
c = m["comparison"]
print("vehicles", c["inputs"]["vehicle_count"])
print("fixed waiting", c["runs"]["fixed"]["total_waiting_time_s"], "replay", m["replays"]["fixed"]["waiting_time_series"])
print("gap_v1 waiting", c["runs"]["adaptive"]["total_waiting_time_s"], "replay", m["replays"]["gap_v1"]["waiting_time_series"])
print("durations", m["replays"]["fixed"]["simulation_duration_s"], m["replays"]["gap_v1"]["simulation_duration_s"], m["video"])
EOF
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,pix_fmt,width,height:format=duration -of default=nw=1 "$D2/videos/annotated.mp4" < /dev/null
```

Then restart the backend (if it does not auto-reload) and select Center Street & University Avenue Intersection on the
AI Traffic page.

If any step fails, the bundle is not valid; do not edit numbers by hand.
Delete only the incomplete `demo2-v1` directory and rerun from step 1.

## Committing (manual)

Commit only the finished bundle files; `runs/`, `reports/comparison-run/`,
`tmp/` and `assets/ai-traffic/inputs/` stay ignored. The video is stored with
Git LFS through `.gitattributes`:

```bash
git lfs install
git add .gitattributes .gitignore
git add -f assets/ai-traffic/versions/demo2-v1/replay_manifest.json \
  assets/ai-traffic/versions/demo2-v1/replays/fixed.jsonl \
  assets/ai-traffic/versions/demo2-v1/replays/gap_v1.jsonl \
  assets/ai-traffic/versions/demo2-v1/reports/comparison_report.json \
  assets/ai-traffic/versions/demo2-v1/videos/annotated.mp4
git lfs ls-files | grep demo2-v1
```

`-f` is only needed in clones whose local `.git/info/exclude` hides
`/assets/ai-traffic/`. Teammates then run `git lfs pull` after pulling.
