# Gate mode sample: youtube, first 30 s

- **Clip:** seconds 0–30 of the cropped top-down clip `$UNIHACK_DIR/youtube/clip.mp4` (1920x1080, 23.976 fps; not in git).
- **Model:** `yolo11s_visdrone` (team-trained on VisDrone), imgsz 960 (544x960 ONNX export), detections cached at score floor 0.10, tracking conf 0.15.
- **Gates:** `backend/vision/config/scenes/youtube.json`.
- **Generated from:** commit `0350662` (`process --scene backend/vision/config/scenes/youtube.json --sample-seconds 30`). It is the start of the full run, cut at `t_s <= 30`.
- **Contents:** `events.jsonl` (115 events) and `counts.jsonl` (31 lines, `t_s` 0–30). Formats are in `docs/DATA_CONTRACTS.md`, sections I and J.
