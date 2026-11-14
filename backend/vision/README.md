# Flowgency vision (P0)

Counts inbound vehicles per visible approach in recorded TfL JamCam clips and
emits **contract A** traffic observations (`docs/DATA_CONTRACTS.md`, section A).
Vision never calls SUMO and never controls signals.

```text
clip -> usability + view check -> YOLO11 detection -> ByteTrack -> directed line crossings -> contract A
```

## Setup

Use a Linux-native virtual environment outside the NTFS-backed repository:

```bash
python3 -m venv ~/.venvs/flowgency-vision
# optional: CPU-only torch (no CUDA GPU on the dev machine; avoids several GB of wheels)
~/.venvs/flowgency-vision/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
~/.venvs/flowgency-vision/bin/pip install -r backend/requirements-vision.txt
```

Verified with Python 3.14.8, torch 2.15.0+cpu, ultralytics 8.4.212,
opencv-python 5.0.0.93, lap 0.5.14. Run commands from the repository root:
`~/.venvs/flowgency-vision/bin/python -m backend.vision.cli <command>`.

## Files and locations

Media, weights, caches, and everything generated live in one **data folder**:
the `UNIHACK_DIR` environment variable when set (e.g. a personal folder outside
the repo), otherwise the repository's gitignored `data/` folder. `$UNIHACK_DIR`
below means that folder. Writing generated output anywhere else inside the repo
is refused. A missing clip, video, or weights file fails with a message saying
where it looked and to set `UNIHACK_DIR` or fill `data/`. The committed samples
(`backend/vision/samples/`) are plain files and need no data folder.

| path | content |
|---|---|
| `backend/vision/config/cameras.json` (repo) | per-camera counting lines in pixels, reference-frame path, `sumo_edge_id` (`null` until verified) |
| `$UNIHACK_DIR/clips/<camera_id>/<YYYYMMDD_HHMMSS>.mp4` | input clips (from `jamcam_fetch.py`) |
| `$UNIHACK_DIR/weights/*.pt` | YOLO11 weights. Stock COCO `yolo11n.pt`/`yolo11m.pt` are downloaded there on first use; the stock COCO yolo11s is stored as `yolo11s_coco.pt` (the old name `yolo11s.pt` is refused) and `yolo11s_visdrone.pt`/`.onnx` are the team's VisDrone weights (never downloaded) |
| `$UNIHACK_DIR/vision_output/observations/<intersection_id>.jsonl` | **contract-A observations, one per usable clip** (rewritten by each `replay`) |
| `$UNIHACK_DIR/vision_output/run_log.csv` | every processed clip: status, skip reason, view evidence, counts, runtime (appended, with `run_id`) |
| `$UNIHACK_DIR/vision_output/reference_frames/` | reference frames saved by `draw-lines` |
| `$UNIHACK_DIR/vision_output/eval/` | `eval_set.csv`, `ground_truth.csv`, `results.csv`, `report.md` |
| `$UNIHACK_DIR/vision_output/demo/` | annotated demo videos |
| `$UNIHACK_DIR/vision_output/cache/` | per-clip scan results, median frames, and detections (safe to delete) |
| `$UNIHACK_DIR/ultralytics_config/` | isolated Ultralytics settings (analytics sync and auto-install off) |

## Commands

| command | purpose |
|---|---|
| `draw-lines --camera <id> [--clip STEM]` | interactive editor: browse clips/frames, add approaches (`<compass>bound_in`), click the line's two ends and then the inbound side; `s` saves `cameras.json` and the frame on screen as the reference |
| `replay --camera <id\|all> [--limit N] [--model yolo11m.pt] [--conf 0.25]` | count and emit observations; `--limit N` takes N clips evenly spaced over the camera's clips |
| `render-demo --camera <id> --clips <N\|stem,stem> --out <mp4>` | annotated video (upscaled x3): boxes, class, track ID, confidence, contact points, lines with arrows, live counters |
| `sample-eval-set [--per-camera 10] [--seed 42] [--day-hours 08-16] [--night-hours 17-07]` | deterministic eval sample of usable clips, half day / half night per camera |
| `label [--camera <id\|all>] [--relabel]` | manual ground truth: loops each eval clip with lines only (no model output); resumable |
| `evaluate [--models a.pt,b.pt] [--confs 0.25,0.40]` (default models `yolo11n.pt,yolo11s_coco.pt,yolo11m.pt`) | scores each model x threshold against the ground truth; writes `report.md` and `results.csv` |

`--config <path>` (before the command) selects another camera config, e.g. for tests.

## Definitions

**Counting rule.** Each approach has a line drawn across its lanes near the
stop line and an inbound point on the side vehicles drive *towards*. A track is
counted once for an approach when its road contact point (bottom-centre of its
box) moves from the upstream side (or exactly on the line) to the inbound side
and the movement crosses the drawn segment within its ends. Movements are
measured between consecutive observations of the track, so short tracking gaps
still count. Outbound crossings are ignored; a track first seen already past the
line is never counted for that approach. Its class is the majority class over
the track's whole life in the clip (ties: higher summed confidence, then name).
COCO `car`, `motorcycle`, `bus`, `truck`, `bicycle` map to the same contract keys.
The counting point is per camera (`counting_point` in `cameras.json`):
`bottom_center` (default, all JamCams) or `center` (top-down views).

**Duplicate suppression.** One vehicle can flip between two box extents with
different labels (a whole-vehicle `truck` box and a smaller `car` box over its
front). Before 2026-11-14 this was counted twice: per-class NMS kept both boxes
in the same frame, and when the box shrank ByteTrack started a new track and
later re-activated the old one, so two track IDs crossed the line (traced in
the J3 and J4 demos). Now NMS ignores labels and also drops a lower-scored box
when at least 85 % of the smaller box lies inside the other, and
`track_filter.DuplicateTrackFilter` maps a newborn track ID onto the track it
duplicates (nested inside a visible track, or overlapping a track lost at most
6 frames earlier). On the 53/50/50 cached clips this lowered the inbound totals
from 47 to 43 (yolo11m), 37 to 35 (yolo11s) and 30 to 26 (yolo11n). Every
changed yolo11m/yolo11s clip was inspected and each removed count was a
duplicate; 3 of the 4 changed yolo11n clips were not inspected. No ground truth was labelled
yet, so the effect on accuracy is not measured.

**Observation fields.**

- `observed_at`: the clip filename is the *download* time in Europe/Bucharest
  local time; it is converted to UTC once when the clip is read and used as the
  window end. TfL publishes clips a few minutes before they are downloaded; the
  time burned into the video was 0-5 minutes earlier in spot checks, so treat
  `observed_at` as approximate (at or slightly after the true window end). In the
  repeated autumn DST hour the earlier instant is used; impossible spring-gap
  times are rejected. Everything internal (logs, reports, eval set) is UTC.
- `window_duration_s`: the analysed duration, i.e. decoded frames after any
  trimmed leading corrupt run, divided by fps. It equals the clip duration (about
  9-10 s) unless the clip starts with corrupt frames (about 5 % of clips, 1-2 s).
- `visible_approaches`: exactly the approaches configured for the camera.
  Unconfigured approaches are absent (unknown), never zero. Zeros for a
  configured approach are measurements. All five class keys plus `total` are
  always present for each visible approach.
- `confidence`: mean, over counted tracks, of each track's mean detection
  confidence; `null` when nothing was counted.
- `model_id`: e.g. `yolo11m.pt+bytetrack`. `source`: `recorded_video`.
  `emergency_detections` is omitted (not evaluated yet).

**Detection and tracking.** YOLO11 runs on CPU at `imgsz` 640 with a score
floor of `min(conf, 0.25)`; detections below `--conf` are dropped and the rest go
to Ultralytics' `BYTETracker` with stock `bytetrack.yaml` (lost-track buffer 30
frames = 1.2 s at 25 fps), with a fresh tracker per clip. This is verified
identical to `model.track(..., tracker="bytetrack.yaml")` (same IDs, classes,
scores and boxes on 3 clips at conf 0.25 and 0.40). Detections are cached per
clip and model, so changing lines or thresholds does not re-run YOLO; the
recorded detection time keeps reported runtimes honest.

**Usability and view check** (`view_check.py`, details and calibration in its
docstring). A clip is skipped, and logged with a reason, when it is a TfL
placeholder card (`placeholder`), under 3 s (`too_short`), has corrupt frames
beyond its trimmed start (`corrupt`), or cannot be tied to the camera's
reference view (`view_changed` / `view_unverified`). The view check matches ORB
features of the clip's median frame against the reference frame (>= 20 RANSAC
inliers with median displacement <= 3 px) and chains matches through
time-adjacent clips so night and moving shadows do not break it. On the
2026-11-12/13 data no camera moved; synthetic pans >= 4 px, tilts and x1.10
zooms were rejected on every camera.

**Day and night** (evaluation only): UTC hour of the window end, which equals
London time in November. Day 08:00-15:59, night 17:00-06:59; the twilight hours
07:00-07:59 and 16:00-16:59 are excluded from the eval sample. Configurable.

## Gate mode (one top-down video)

A second, independent mode for one recorded top-down video of one intersection
(currently `$UNIHACK_DIR/youtube/clip.mp4`, 1920x1080, 23.976 fps, 6329 decoded
frames). It writes **contract I** gate events and **contract J** per-second
counts (`docs/DATA_CONTRACTS.md`). The London line-counting mode above is unchanged.
Teammate setup and consumer notes: `backend/vision/COLLEAGUE_SETUP.md`.
Both files are committed for the youtube clip: `backend/vision/samples/youtube_30s/` (first 30 s, for quick
development) and `backend/vision/samples/youtube_full/` (264 s, for the simulation).

```text
scene JSON (12 gates) -> detect (YOLO once, cached) -> process (ByteTrack -> gates) -> events.jsonl, counts.jsonl, gate_run.json
```

| command | purpose |
|---|---|
| `draw-gates --scene backend/vision/config/scenes/<id>.json [--video V]` | interactive editor for the 12 gates (`<arm>_in.far`, `<arm>_in.stop`, `<arm>_out`); `r` redraws a gate (4 clicks), `s` saves the scene and a preview `<scene output>/<id>_gates.jpg` |
| `detect --scene S [--no-cache]` | runs the scene's detector profile over every frame once; cached under `cache/gate_detections/<model>_imgsz<N>_floor0.10/` with a JSON sidecar (backend, weights, timing, fallback reason) |
| `process --scene S [--sample-seconds 30]` | tracks the cached detections and writes `events.jsonl`, `counts.jsonl`, `gate_run.json` to `vision_output/<scene_id>/`; `--sample-seconds N` also writes the first N s to `sample_<N>s/` for sharing |
| `render-gate-demo --scene S [--start-s A --end-s B] [--scale 0.667]` | 1280x720 demo: tracks coloured by arm, gates flashing on triggers, and the `counts.jsonl` line consumers would read at that moment |

**Detector per scene.** The scene's `model_id` picks a profile in
`detections.py`. Top-down: `yolo11s_visdrone` (team-trained on VisDrone,
`car`/`van`/`truck`/`bus`/`motor` merged into `vehicle`), imgsz 960, conf 0.15,
detections cached at a 0.10 floor. A static 544x960 ONNX export is used when the
video letterboxes to exactly 544x960 (any 16:9 size); otherwise the `.pt` is used
and the reason is logged and stored in the cache sidecar and `gate_run.json`.
COCO weights find no vehicles top-down (they label cars `cell phone`).

**Speed (CPU, i7-1265U).** Detection 163 ms/frame with the ONNX export (17 min
for the clip, once); `process` about 16 s; demo render a few minutes.

**One entry per track.** Only a track's first stop-gate trigger is an
`intersection_entered` event and a discharge. Later stop-gate triggers by the
same track are suppressed as `already_entered`. On the youtube clip these are
left-turners whose curve clips another arm's stop gate: south -> west turners
cross the top-right corner of `west_in.stop`, and east -> south turners cross
the top-left corner of `south_in.stop`. Before this rule they caused false
discharges, 101 clamps, and ambiguous `origin_arm` values.

**`gate_run.json`.** Initial state (track IDs per approach and in the junction),
unsuppressed triggers per gate, every suppressed trigger (reason, frame,
counting point `x`/`y`, and for `already_entered` the gate of the track's entry),
`already_entered_by_gate_pair`, every clamp, `origin_arm` null reasons, scene
warnings, detector provenance, and `tracking`: track count
and tracks whose counting point never spans 20 px over the clip
(`static_tracks`, parked vehicles) with those among the initial counts
(`static_initial_tracks`; `process` warns when it is not empty). On the current
clip 21 tracks are static and none is counted in the initial state.

## Status and known limitations

- Accuracy is **not yet measured**; see `vision_output/eval/report.md` once the
  ground truth is labelled. Counts are camera evidence for a short window, not
  demand estimates.
- CPU only on the dev machine: about 12 s (`yolo11n`), 33 s (`yolo11s`) and
  95 s (`yolo11m`) per 10 s clip.
- Each camera currently has one approach, drawn far from the camera, where
  vehicles are small at 352x288; distant and night detection is the main risk.
- COCO labels most vans `truck`, so the `car`/`truck` split is biased towards
  `truck`; totals are unaffected.
- `sumo_edge_id` is `null` everywhere: camera-to-SUMO mappings are unverified
  (`scenarios/london_network/mapping_candidates.json`).
- Emergency-vehicle detection is not implemented.
- The view check misses pure camera roll (PTZ cameras do not roll) and, when a
  view change splits the timeline, may skip unaffected clips beyond it as
  `view_unverified` (safe: skipped, not miscounted).
- Demo videos are MPEG-4 Part 2 (`mp4v`) because the pip OpenCV build has no
  H.264 encoder; they play in VLC but may not play in browsers.

## Tests

```bash
# pure tests (system Python is enough; CV tests are skipped)
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_vision_counting tests.test_vision_clips \
  tests.test_vision_contract tests.test_vision_config tests.test_vision_draw_lines tests.test_vision_evaluation
# everything, including view check and pipeline on synthetic media
PYTHONDONTWRITEBYTECODE=1 ~/.venvs/flowgency-vision/bin/python -m unittest discover -s tests -p "test_vision_*.py"
```
