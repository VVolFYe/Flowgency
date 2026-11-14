# Gate mode: setup and run (for teammates)

How to reproduce the top-down gate outputs (`events.jsonl`, `counts.jsonl`)
on your own machine, and what to read if you only consume them. Formats and
semantics are in `docs/DATA_CONTRACTS.md`, sections **I** (events) and **J**
(per-second counts). Background and definitions: `backend/vision/README.md`,
section "Gate mode".

## Only consuming the outputs

You need nothing beyond a fresh clone of `feat/traffic-ai`: no setup, no
data folder, no `UNIHACK_DIR`. Both samples are plain files in the repository,
each with a README giving clip, model, gates, and source commit:

| folder | content | use it for |
|---|---|---|
| `backend/vision/samples/youtube_30s/` | first 30 s (115 events, 31 counts lines) | quick development and tests |
| `backend/vision/samples/youtube_full/` | whole clip, 264 s (985 events, 264 counts lines) | the simulation |

The 30 s files are an exact prefix of the full ones. Read them line by line as JSON:

- `events.jsonl`: one event per gate trigger (`approach_entered`,
  `intersection_entered`, `intersection_exited`), in time order, with `t_s`
  seconds from the start of the video.
- `counts.jsonl`: one line per whole second (`t_s` = 0, 1, 2, ...) with
  `vehicles_on_approach`, `entered_total`, `discharged_total` per arm and
  `in_intersection`.

Rules that matter for consumers:

- Arms are named by **image side** (`north` = top of the frame), not by compass
  bearing; mapping them to SUMO approaches is a separate, unverified step.
- A missing arm or a `null` value means **unknown**, never zero.
- Counts are camera estimates that can drift over the video; they are not SUMO
  queue lengths. Clamps (a count that would go below zero) are listed in
  `gate_run.json`.
- `origin_arm` on `intersection_exited` is `null` when it is not known; it is
  never guessed.

## Videos (Google Drive)

Drive link: <ask Vlad>

The videos are **only needed for the demo**. The simulation data in
`backend/vision/samples/` works without them.

| file on Drive | goes to (relative to the repository root) |
|---|---|
| `clip.mp4`: the raw top-down clip | `data/youtube/clip.mp4` |
| `youtube_gates_demo.mp4`: the gates demo (tracks, gates, live counts) | `data/vision_output/youtube/demo/youtube_gates_demo.mp4` |

`data/` is the default data folder and is gitignored. If you set
`UNIHACK_DIR`, use the same layout under that folder instead of `data/`.
Example, from the repository root, with the files downloaded to `~/Downloads`:

```bash
mkdir -p data/youtube data/vision_output/youtube/demo
mv ~/Downloads/clip.mp4 data/youtube/clip.mp4
mv ~/Downloads/youtube_gates_demo.mp4 data/vision_output/youtube/demo/youtube_gates_demo.mp4
```

Check them (needs the vision venv from the next section). It prints the
expected paths for anything missing and checks that each video is as long as
the 264 s outputs:

```bash
~/.venvs/flowgency-vision/bin/python -m backend.vision.cli check-videos
```

- **Timing:** video time `t` (seconds from the first frame) equals `t_s` in
  `events.jsonl` and `counts.jsonl`. Frame `n` is at `t = n / 23.976`. Both
  videos have the same 6329 frames, so a moment in the demo and the same moment
  in the raw clip have the same `t`.
- **Which video to show:** the gates demo goes next to the simulation. Its panel
  shows the `counts.jsonl` line a consumer reads at that moment. The raw clip
  is the unannotated input.
- The videos are MPEG-4 Part 2; play them in VLC (browsers may refuse them).

## Running the pipeline yourself

Nothing below goes into git. Video, weights, caches, and outputs live in a
data folder: by default the repository's own `data/` folder (gitignored), or
any folder you name with the `UNIHACK_DIR` environment variable
(`export UNIHACK_DIR=~/flowgency-data`). `$UNIHACK_DIR` below means whichever
of the two you use. If an input is missing, the command stops and says where it
looked. The code refuses to write outputs to tracked repository paths.

1. A Python virtual environment **outside** the repository, which may sit on an NTFS mount
   (verified with Python 3.14.8):

   ```bash
   python3 -m venv ~/.venvs/flowgency-vision
   # CPU-only torch avoids several GB of CUDA wheels:
   ~/.venvs/flowgency-vision/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
   ~/.venvs/flowgency-vision/bin/pip install -r backend/requirements-vision.txt
   ```

2. The clip is not downloadable by the code: get it from the vision owner or the Drive (see
   "Videos (Google Drive)") and put it at `$UNIHACK_DIR/youtube/clip.mp4`.

   Team weights are downloaded automatically on first use from the `weights-v1` GitHub
   release and checked against their sha256 (`backend/vision/weights.py`):

   | file | lands at |
   |---|---|
   | team-trained VisDrone weights | `$UNIHACK_DIR/weights/yolo11s_visdrone.pt` |
   | its 544x960 ONNX export (faster) | `$UNIHACK_DIR/weights/yolo11s_visdrone_544x960.onnx` |

   Without `onnxruntime` the `.pt` is used and a
   `detector fallback:` line says why. The same happens for a video whose aspect
   ratio is not 16:9. VisDrone-derived weights are non-commercial
   (CC BY-NC-SA 3.0).

3. From the repository root:

   ```bash
   PY=~/.venvs/flowgency-vision/bin/python
   SCENE=backend/vision/config/scenes/youtube.json
   $PY -m backend.vision.cli detect --scene $SCENE          # once; ~17 min on a laptop CPU, cached
   $PY -m backend.vision.cli process --scene $SCENE --sample-seconds 30
   $PY -m backend.vision.cli render-gate-demo --scene $SCENE   # optional demo video
   ```

   Outputs go to `$UNIHACK_DIR/vision_output/youtube/`: `events.jsonl`,
   `counts.jsonl`, `gate_run.json`, `sample_30s/`, and `demo/youtube_gates_demo.mp4`
   (MPEG-4 Part 2: plays in VLC, maybe not in browsers).

4. Changing gates: `$PY -m backend.vision.cli draw-gates --scene $SCENE`, then
   `process` again. Detection is not re-run; the cache is reused.

## Checks

```bash
PYTHONDONTWRITEBYTECODE=1 ~/.venvs/flowgency-vision/bin/python -m unittest discover -s tests -p "test_vision_*.py"
```

No media or weights are needed for the tests.
