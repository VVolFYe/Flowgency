"""Vision command-line entry points: ``python -m backend.vision.cli <command>``.

All timestamps printed or written are UTC. Inputs and outputs live under
``UNIHACK_DIR`` (see ``paths.py``); only ``config/cameras.json`` is in the repo.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from .clips import discover_clips, format_utc
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


def _periods(args: argparse.Namespace):
    from .evaluation import PeriodConfig

    return PeriodConfig.parse(args.day_hours, args.night_hours)


def cmd_sample_eval_set(args: argparse.Namespace) -> int:
    from .clips import format_utc
    from .evaluation import EVAL_SET_FIELDS, EvalCandidate, read_csv, sample_eval_set, write_csv
    from .pipeline import CameraContext, ensure_outside_repo

    paths = _paths()
    periods = _periods(args)
    out = ensure_outside_repo(paths.eval_dir / "eval_set.csv")
    candidates = {}
    for camera in load_cameras(args.config).cameras:
        context = CameraContext.build(camera, paths, progress=_log)
        usable = context.usable_clips()
        candidates[camera.camera_id] = [
            EvalCandidate(camera.intersection_id, camera.camera_id, c.name, format_utc(c.observed_at_utc),
                          periods.classify(c.observed_at_utc))
            for c in usable
        ]
        pool = candidates[camera.camera_id]
        _log(f"{camera.intersection_id} {camera.camera_id}: {len(usable)}/{len(context.clips)} usable; "
             f"day {sum(c.period == 'day' for c in pool)}, night {sum(c.period == 'night' for c in pool)}, "
             f"twilight {sum(c.period == 'twilight' for c in pool)} (excluded)")
    report = sample_eval_set(candidates, args.per_camera, args.seed)
    existing = read_csv(out)
    new_rows = [{k: str(v) for k, v in r.items()} for r in report.rows]
    if existing and existing != new_rows and not args.force:
        labelled = len(read_csv(paths.eval_dir / "ground_truth.csv"))
        raise SystemExit(f"{out} exists with a different sample ({labelled} ground-truth rows); "
                         "use --force to overwrite")
    write_csv(out, EVAL_SET_FIELDS, report.rows)
    for note in report.notes:
        _log(f"NOTE {note}")
    for camera_id in sorted(candidates):
        rows = [r for r in report.rows if r["camera_id"] == camera_id]
        _log(f"{camera_id}: {len(rows)} clips (day {sum(r['period'] == 'day' for r in rows)}, "
             f"night {sum(r['period'] == 'night' for r in rows)})")
    _log(f"wrote {out}")
    return 0


def cmd_label(args: argparse.Namespace) -> int:
    from .clips import find_clip, read_frames
    from .evaluation import GT_FIELDS, read_csv, write_csv
    from .label import LabelItem, is_complete, run_label_gui
    from .pipeline import CameraContext, ensure_outside_repo

    paths = _paths()
    eval_rows = read_csv(paths.eval_dir / "eval_set.csv")
    if not eval_rows:
        raise SystemExit("no eval set; run sample-eval-set first")
    gt_path = ensure_outside_repo(paths.eval_dir / "ground_truth.csv")
    gt_rows = read_csv(gt_path)
    config = load_cameras(args.config)
    wanted = sorted({r["camera_id"] for r in eval_rows if args.camera in ("all", r["camera_id"])})
    if not wanted:
        raise SystemExit(f"camera {args.camera} is not in the eval set")
    contexts = {cam: CameraContext.build(config.get(cam), paths, progress=_log) for cam in wanted}

    def loader(row: dict[str, str]):
        def load() -> list:
            clip = find_clip(paths.clips_dir, f"{row['camera_id']}/{row['clip']}")
            scan = contexts[row["camera_id"]].decision(clip).scan
            frames = read_frames(clip.path)
            if scan is None:
                return frames
            bad = set(scan.corrupt_frames)
            return [f for i, f in enumerate(frames) if i >= scan.start_frame and i not in bad]
        return load

    items = []
    for row in sorted((r for r in eval_rows if r["camera_id"] in wanted), key=lambda r: (r["intersection_id"], r["clip"])):
        existing = [g for g in gt_rows if g["camera_id"] == row["camera_id"] and g["clip"] == row["clip"]]
        items.append(LabelItem(row, contexts[row["camera_id"]].camera, loader(row), existing))
    todo = [i for i, item in enumerate(items) if not is_complete(item.existing, item.camera.approach_ids)]
    _log(f"{len(items)} eval clips, {len(items) - len(todo)} already labelled")
    if not todo and not args.relabel:
        _log("all clips labelled; use --relabel to review")
        return 0

    def save_rows(eval_row: dict[str, str], rows: list[dict]) -> None:
        nonlocal gt_rows
        gt_rows = [g for g in gt_rows if not (g["camera_id"] == eval_row["camera_id"] and g["clip"] == eval_row["clip"])]
        gt_rows += [{k: str(v) for k, v in r.items()} for r in rows]
        gt_rows.sort(key=lambda g: (g["intersection_id"], g["clip"], g["approach_id"]))
        write_csv(gt_path, GT_FIELDS, gt_rows)
        for item in items:
            if item.eval_row is eval_row:
                item.existing = [g for g in gt_rows if g["camera_id"] == eval_row["camera_id"] and g["clip"] == eval_row["clip"]]
        _log(f"saved {eval_row['camera_id']} {eval_row['clip']}: "
             + ", ".join(f"{r['approach_id']}={r['total'] or r['status']}" for r in rows))

    run_label_gui(items, save_rows, start=0 if args.relabel else todo[0])
    remaining = sum(not is_complete(i.existing, i.camera.approach_ids) for i in items)
    _log(f"ground truth: {gt_path} ({len(items) - remaining}/{len(items)} clips done)")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    from .clips import find_clip
    from .counting import VEHICLE_CLASSES
    from .detect_track import VehicleTracker
    from .evaluation import (
        RESULT_FIELDS, Pair, Targets, load_ground_truth, read_csv, render_report, write_csv,
    )
    from .pipeline import CameraContext, ensure_outside_repo, process_clip

    paths = _paths()
    periods = _periods(args)
    eval_rows = read_csv(args.eval_set or paths.eval_dir / "eval_set.csv")
    gt_path = args.ground_truth or paths.eval_dir / "ground_truth.csv"
    labels, unusable = load_ground_truth(read_csv(gt_path))
    out_dir = ensure_outside_repo(args.out_dir or paths.eval_dir)
    config = load_cameras(args.config)
    contexts: dict[str, CameraContext] = {}
    notes: list[str] = []
    jobs = []
    for row in eval_rows:
        camera = config.get(row["camera_id"])
        if (row["camera_id"], row["clip"]) in unusable:
            notes.append(f"{row['camera_id']} {row['clip']}: marked unusable by labeller; excluded")
            continue
        if not all((row["camera_id"], row["clip"], a) in labels for a in camera.approach_ids):
            notes.append(f"{row['camera_id']} {row['clip']}: not (fully) labelled; excluded")
            continue
        if row["camera_id"] not in contexts:
            contexts[row["camera_id"]] = CameraContext.build(camera, paths, progress=_log)
        jobs.append((row, camera))
    if not jobs:
        raise SystemExit(f"no labelled eval clips found in {gt_path}")
    _log(f"evaluating {len(jobs)} labelled clips")

    pairs: list[Pair] = []
    result_rows = []
    for model in args.models.split(","):
        for conf in (float(c) for c in args.confs.split(",")):
            tracker = VehicleTracker(paths, model, conf=conf, imgsz=args.imgsz)
            for n, (row, camera) in enumerate(jobs, 1):
                clip = find_clip(paths.clips_dir, f"{row['camera_id']}/{row['clip']}")
                result = process_clip(clip, contexts[row["camera_id"]].decision(clip), camera, tracker)
                runtime = result.pipeline_runtime_s
                for approach in camera.approach_ids:
                    gt = labels[(row["camera_id"], row["clip"], approach)]
                    pred = result.counts.counts_by_approach[approach] if result.counts else None
                    if pred is None:
                        notes.append(f"{model} {conf}: {row['clip']} pipeline {result.status} "
                                     f"({result.reason}: {result.detail}); scored as 0 predicted")
                    pred_total = pred["total"] if pred else 0
                    pairs.append(Pair(model, conf, row["intersection_id"], row["camera_id"], row["clip"],
                                      row["period"], approach, gt.total, pred_total, runtime))
                    result_rows.append({
                        "model": model, "conf": conf, "intersection_id": row["intersection_id"],
                        "camera_id": row["camera_id"], "clip": row["clip"], "observed_at_utc": row["observed_at_utc"],
                        "period": row["period"], "approach_id": approach, "gt_total": gt.total,
                        "pred_total": pred_total, "error": pred_total - gt.total, "abs_error": abs(pred_total - gt.total),
                        **{f"gt_{c}": (gt.split or {}).get(c, "") for c in VEHICLE_CLASSES},
                        **{f"pred_{c}": (pred or {}).get(c, "") for c in VEHICLE_CLASSES},
                        "pipeline_status": result.status,
                        "runtime_s": "" if runtime is None else f"{runtime:.2f}",
                    })
                _log(f"  {model} conf {conf} [{n}/{len(jobs)}] {row['camera_id']} {row['clip']}: "
                     + ", ".join(f"{a} gt={labels[(row['camera_id'], row['clip'], a)].total} "
                                 f"pred={result.counts.counts_by_approach[a]['total'] if result.counts else 'n/a'}"
                                 for a in camera.approach_ids)
                     + f" [{runtime or 0:.1f}s]")
    write_csv(out_dir / "results.csv", RESULT_FIELDS, result_rows)
    report = render_report(pairs, targets=Targets(), periods=periods, notes=sorted(set(notes)),
                           generated_utc=format_utc(datetime.now(UTC)))
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    _log(f"wrote {out_dir / 'report.md'} and {out_dir / 'results.csv'}")
    print(report)
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

    def add_period_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--day-hours", default="08-16", help="UTC day hours [start-end), default 08-16")
        p.add_argument("--night-hours", default="17-07", help="UTC night hours [start-end), default 17-07")

    p = sub.add_parser("sample-eval-set", help="pick a deterministic day/night eval sample of usable clips")
    p.add_argument("--per-camera", type=int, default=10)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--force", action="store_true", help="overwrite an existing, different eval set")
    add_period_args(p)
    p.set_defaults(func=cmd_sample_eval_set)

    p = sub.add_parser("label", help="label ground-truth inbound counts for the eval set (no model output shown)")
    p.add_argument("--camera", default="all", help="JamCam ID or 'all'")
    p.add_argument("--relabel", action="store_true", help="start at the first clip even if labelled")
    p.set_defaults(func=cmd_label)

    p = sub.add_parser("evaluate", help="score models x confidence thresholds against the ground truth")
    p.add_argument("--models", default="yolo11n.pt,yolo11s.pt,yolo11m.pt")
    p.add_argument("--confs", default="0.25,0.40")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--eval-set", type=Path, help="default UNIHACK_DIR/vision_output/eval/eval_set.csv")
    p.add_argument("--ground-truth", type=Path, help="default UNIHACK_DIR/vision_output/eval/ground_truth.csv")
    p.add_argument("--out-dir", type=Path, help="default UNIHACK_DIR/vision_output/eval")
    add_period_args(p)
    p.set_defaults(func=cmd_evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
