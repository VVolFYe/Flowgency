"""Vision command-line entry points: ``python -m backend.vision.cli <command>``.

All timestamps printed or written are UTC. Inputs and outputs live under
``UNIHACK_DIR`` (see ``paths.py``); only ``config/cameras.json`` is in the repo.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from .clips import discover_clips
from .config import load_camera_registry, load_cameras
from .paths import DEFAULT_CAMERAS_JSON, VisionPaths


def _paths() -> VisionPaths:
    return VisionPaths.from_env()


def cmd_draw_lines(args: argparse.Namespace) -> int:
    from .draw_lines import run_draw_lines

    paths = _paths()
    registry = load_camera_registry()
    if args.camera not in registry:
        print(f"unknown camera {args.camera}; known: {', '.join(sorted(registry))}", file=sys.stderr)
        return 2
    config = load_cameras(args.config, missing_ok=True)
    run_draw_lines(
        camera_id=args.camera,
        intersection_id=registry[args.camera],
        clips=discover_clips(paths.clips_dir, args.camera),
        config=config,
        config_path=args.config,
        reference_dir=paths.reference_frames_dir,
        to_relative=paths.relative,
        start_clip=args.clip,
        scale=args.scale,
    )
    return 0


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _selected_cameras(args: argparse.Namespace):
    config = load_cameras(args.config)
    if args.camera == "all":
        if not config.cameras:
            raise SystemExit("no cameras configured; run draw-lines first")
        return config.cameras
    return [config.get(args.camera)]


def _tracker(args: argparse.Namespace):
    from .detect_track import VehicleTracker

    return VehicleTracker(_paths(), args.model, conf=args.conf, imgsz=args.imgsz)


def cmd_replay(args: argparse.Namespace) -> int:
    from collections import Counter, defaultdict

    from .clips import format_utc
    from .pipeline import (
        CameraContext, append_run_log, new_run_id, process_clip, run_log_row, select_evenly,
        write_observations,
    )

    paths = _paths()
    cameras = _selected_cameras(args)
    tracker = _tracker(args)
    run_id, started = new_run_id(), format_utc(datetime.now(UTC))
    by_intersection: dict[str, list[dict]] = defaultdict(list)
    rows: list[dict] = []
    exit_code = 0
    for camera in cameras:
        if not camera.approaches:
            _log(f"{camera.camera_id}: no approaches configured; skipping camera")
            exit_code = 1
            continue
        _log(f"{camera.intersection_id} {camera.camera_id}: building view index")
        context = CameraContext.build(camera, paths, progress=_log)
        selected = select_evenly(context.clips, args.limit)
        reasons: Counter[str] = Counter()
        totals: Counter[str] = Counter()
        runtimes = []
        for n, clip in enumerate(selected, 1):
            result = process_clip(clip, context.decision(clip), camera, tracker)
            rows.append(run_log_row(result, camera, run_id, started, tracker.model_id, args.conf))
            reasons[result.status if result.status == "ok" else f"{result.status}:{result.reason}"] += 1
            if result.status == "ok":
                by_intersection[camera.intersection_id].append(result.observation)
                runtimes.append(result.runtime_s)
                for approach_id, by_class in result.counts.counts_by_approach.items():
                    totals[approach_id] += by_class["total"]
            elif result.status == "error":
                exit_code = 1
            _log(f"  [{n}/{len(selected)}] {clip.name} ({format_utc(clip.observed_at_utc)}) "
                 f"{result.status}{' ' + str(result.reason) if result.reason else ''}: "
                 + (", ".join(f"{a}={c['total']}" for a, c in result.counts.counts_by_approach.items())
                    if result.counts else result.detail)
                 + f" [{result.runtime_s:.1f}s]")
        mean_rt = sum(runtimes) / len(runtimes) if runtimes else 0.0
        _log(f"  summary {camera.camera_id}: {dict(reasons)}; inbound totals {dict(totals)}; "
             f"mean runtime {mean_rt:.1f}s/clip")
    for intersection_id, observations in by_intersection.items():
        write_observations(paths.observations_dir / f"{intersection_id}.jsonl", observations)
    append_run_log(paths.run_log_csv, rows)
    _log(f"run {run_id}: wrote {sum(map(len, by_intersection.values()))} observations to "
         f"{paths.observations_dir}; log {paths.run_log_csv}")
    return exit_code


def cmd_render_demo(args: argparse.Namespace) -> int:
    from .pipeline import CameraContext, select_evenly
    from .render import render_demo

    paths = _paths()
    camera = load_cameras(args.config).get(args.camera)
    context = CameraContext.build(camera, paths, progress=_log)
    if args.clips.isdigit():
        clips = select_evenly(context.usable_clips(), int(args.clips))
    else:
        by_name = {c.name: c for c in context.clips}
        missing = [s for s in args.clips.split(",") if s not in by_name]
        if missing:
            raise SystemExit(f"unknown clips for {camera.camera_id}: {missing}")
        clips = [by_name[s] for s in args.clips.split(",")]
    results = render_demo(context, clips, _tracker(args), args.out, scale=args.scale)
    for result in results:
        counts = result.counts.counts_by_approach if result.counts else None
        _log(f"  {result.clip.name}: {result.status} {result.reason or ''} "
             + (", ".join(f"{a}={c['total']}" for a, c in counts.items()) if counts else result.detail))
    _log(f"wrote {args.out}")
    return 0


def _add_model_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--model", default="yolo11m.pt", help="weights file name under UNIHACK_DIR/weights")
    p.add_argument("--conf", type=float, default=0.25, help="detector confidence threshold fed to ByteTrack")
    p.add_argument("--imgsz", type=int, default=640, help="YOLO inference size")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backend.vision.cli", description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CAMERAS_JSON,
        help="camera line config (default: backend/vision/config/cameras.json)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("draw-lines", help="draw per-approach counting lines for one camera")
    p.add_argument("--camera", required=True, help="JamCam ID, e.g. JamCams_00001.04503")
    p.add_argument("--clip", help="start at this clip stem (YYYYMMDD_HHMMSS); default latest daytime clip")
    p.add_argument("--scale", type=int, default=3, help="display upscale factor (default 3)")
    p.set_defaults(func=cmd_draw_lines)

    p = sub.add_parser("replay", help="count vehicles in recorded clips and emit contract-A observations")
    p.add_argument("--camera", required=True, help="JamCam ID or 'all'")
    p.add_argument("--limit", type=int, help="process N clips evenly spaced over the camera's clips")
    _add_model_args(p)
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("render-demo", help="write an annotated demo video")
    p.add_argument("--camera", required=True)
    p.add_argument("--clips", required=True, help="N (evenly spaced usable clips) or comma-separated clip stems")
    p.add_argument("--out", type=Path, required=True, help="output .mp4 (must be outside the repo)")
    p.add_argument("--scale", type=int, default=3, help="upscale factor for legibility (default 3)")
    _add_model_args(p)
    p.set_defaults(func=cmd_render_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
