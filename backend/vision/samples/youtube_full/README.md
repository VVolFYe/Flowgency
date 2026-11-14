# Gate mode sample: youtube, full clip (264 s)

- **Clip:** the whole cropped top-down clip `$UNIHACK_DIR/youtube/clip.mp4` (0–264 s, 6329 frames, 1920x1080, 23.976 fps; not in git).
- **Model:** `yolo11s_visdrone` (team-trained on VisDrone), imgsz 960 (544x960 ONNX export), detections cached at score floor 0.10, tracking conf 0.15.
- **Gates:** `backend/vision/config/scenes/youtube.json`.
- **Generated from:** commit `19402b2` (`process --scene backend/vision/config/scenes/youtube.json`). Regenerating at `7daa2df` gives byte-identical files. This run uses the one-entry-per-track rule: 0 clamps, 6 of 329 exits with `origin_arm` null (5 `in_junction_at_start`, 1 `no_entry_seen`).
- **Contents:** `events.jsonl` (985 events) and `counts.jsonl` (264 lines, `t_s` 0–263). Formats are in `docs/DATA_CONTRACTS.md`, sections I and J. The first 30 s are identical to `../youtube_30s/`.
