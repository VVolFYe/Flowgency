# Gate mode: setup and run (for teammates)

How to reproduce the top-down gate outputs (`events.jsonl`, `counts.jsonl`)
on your own machine, and what to read if you only consume them. Formats and
semantics are in `docs/DATA_CONTRACTS.md`, sections **I** (events) and **J**
(per-second counts). Background and definitions: `backend/vision/README.md`,
section "Gate mode".

## Only consuming the outputs

You do not need any of the setup below. A 30 s sample is in the repository at
`backend/vision/samples/youtube_30s/` (`events.jsonl`, `counts.jsonl`, and a
README with its provenance). Ask the vision owner for the files of a full run.
Read them line by line as JSON:

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

## Running the pipeline yourself

Nothing below goes into git: video, weights, caches, and outputs live under
the folder named by the `UNIHACK_DIR` environment variable, outside the
repository. Set it before running anything (`export UNIHACK_DIR=~/unihack`);
the built-in default in `backend/vision/paths.py` is the vision owner's own
machine. The code refuses to write outputs inside the repository.

1. A Python virtual environment **outside** the repository, which may sit on an NTFS mount
   (verified with Python 3.14.8):

   ```bash
   python3 -m venv ~/.venvs/flowgency-vision
   # CPU-only torch avoids several GB of CUDA wheels:
   ~/.venvs/flowgency-vision/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
   ~/.venvs/flowgency-vision/bin/pip install -r backend/requirements-vision.txt
   ```

2. Files to obtain from the vision owner (not downloadable by the code):

   | file | put it at |
   |---|---|
   | the clip | `$UNIHACK_DIR/youtube/clip.mp4` |
   | team-trained VisDrone weights | `$UNIHACK_DIR/weights/yolo11s_visdrone.pt` |
   | its 544x960 ONNX export (optional, faster) | `$UNIHACK_DIR/weights/yolo11s_visdrone_544x960.onnx` |

   Without the ONNX file (or without `onnxruntime`) the `.pt` is used and a
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
