"""Vision command-line entry points: ``python -m backend.vision.cli <command>``.

All timestamps printed or written are UTC. Inputs and outputs live under
``UNIHACK_DIR`` (see ``paths.py``); only ``config/cameras.json`` is in the repo.
"""

from __future__ import annotations

import argparse
import sys
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
