# Gate mode sample: youtube2 (second intersection), full clip (156 s)

- **Clip:** the whole top-down clip `$UNIHACK_DIR/youtube/clip2.mp4` (0–156 s, 3741 frames, 1920x1080, 23.976 fps; not in git).
- **Model:** `yolo11s_visdrone` (team-trained on VisDrone), imgsz 960 (544x960 ONNX export), detections cached at score floor 0.10, tracking conf 0.15.
- **Gates:** `backend/vision/config/scenes/youtube2.json` (travel lanes only; parked cars are excluded by position).
- **Generated from:** commit `0a4236b`, causal gate engine (`process --scene backend/vision/config/scenes/youtube2.json`). The code at `d2d8684` produces identical lines.
- **Run:** 403 events: 129 `approach_entered` via `far_gate`, 3 via `region`, 3 `approach_left` via `region`, 132 `intersection_entered`, 136 `intersection_exited`. 3 `in_intersection` clamps; 8 of 136 exits have `origin_arm` null (6 `in_junction_at_start`, 2 `no_entry_seen`).
- **Contents:** `events.jsonl` (403 events) and `counts.jsonl` (156 lines, `t_s` 0–155; lines 0–2 are before the warm-up and unknown). Formats are in `docs/DATA_CONTRACTS.md`, sections I and J. The first 30 s are identical to `../youtube2_30s/`.
- **Known limit:** right-turners from the west arm run at y ≈ 688–695 near the junction, on the bottom edge of the west in-gates (y 690). Two of them (#550, #10) miss `west_in.stop` and leave the west approach as `approach_left` via `region` instead of discharging.
