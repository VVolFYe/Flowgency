# Gate mode sample: youtube2 (second intersection), first 30 s

- **Clip:** seconds 0–30 of the top-down clip `$UNIHACK_DIR/youtube/clip2.mp4` (a second intersection from the same stream, cut 4:48–7:24; 1920x1080, 23.976 fps; not in git).
- **Model:** `yolo11s_visdrone` (team-trained on VisDrone), imgsz 960 (544x960 ONNX export), detections cached at score floor 0.10, tracking conf 0.15.
- **Gates:** `backend/vision/config/scenes/youtube2.json` (travel lanes only; parked cars are excluded by position).
- **Generated from:** commit `0a4236b`, causal gate engine (`process --scene backend/vision/config/scenes/youtube2.json --sample-seconds 30`). It is the start of the full run, cut at `t_s <= 30`.
- **Contents:** `events.jsonl` (59 events) and `counts.jsonl` (31 lines, `t_s` 0–30). Lines `t_s` 0–2 are before the 2 s warm-up: `approaches` is `{}` and `in_intersection` is `null` (unknown). Formats are in `docs/DATA_CONTRACTS.md`, sections I and J.
