"""Prepare external browser assets and a validated AI Traffic replay manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from backend.api.replay_assets import validate_comparison_report
from backend.simulation.replay import inspect_replay


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _probe_video(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,pix_fmt:format=duration",
            "-of", "json", str(path),
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    value = json.loads(completed.stdout)
    stream = value["streams"][0]
    return {
        "duration_s": round(float(value["format"]["duration"]), 6),
        "codec": stream["codec_name"],
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "pixel_format": stream.get("pix_fmt"),
    }


def _prepare_video(source: Path, target: Path) -> dict[str, Any]:
    if target.exists():
        raise FileExistsError(f"refusing to overwrite video asset: {target}")
    source_metadata = _probe_video(source)
    if source_metadata["codec"] == "h264" and source_metadata["pixel_format"] == "yuv420p":
        shutil.copy2(source, target)
        conversion = "copied_existing_h264"
    else:
        subprocess.run(
            [
                "ffmpeg", "-v", "warning", "-i", str(source),
                "-map", "0:v:0", "-an", "-c:v", "libx264", "-preset", "medium",
                "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(target),
            ],
            check=True,
        )
        conversion = f"transcoded_from_{source_metadata['codec']}_to_h264"
    output_metadata = _probe_video(target)
    if output_metadata["codec"] != "h264" or output_metadata["pixel_format"] != "yuv420p":
        raise ValueError(f"browser video output is incompatible: {target}")
    return {
        **output_metadata,
        "conversion": conversion,
        "source_sha256": _sha256(source),
        "sha256": _sha256(target),
        "size_bytes": target.stat().st_size,
    }


def create_bundle(
    output_directory: Path,
    *,
    original_video: Path,
    annotated_video: Path,
    fixed_replay: Path,
    gap_replay: Path,
    fixed_run_report: Path,
    adaptive_run_report: Path,
    comparison_report: Path,
    dataset_id: str,
    require_waiting_series: bool = False,
) -> Path:
    root = output_directory.resolve()
    if not root.is_dir():
        raise ValueError("external replay output directory must already exist")
    if not os.access(root, os.W_OK):
        raise PermissionError("external replay output directory is not writable")
    if not root.is_mount() and str(root).startswith("/tmp"):
        raise ValueError("large replay bundles must not be generated under /tmp")
    videos = root / "videos"
    replays = root / "replays"
    reports = root / "reports"
    for directory in (videos, replays, reports):
        directory.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "replay_manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"refusing to overwrite replay manifest: {manifest_path}")

    fixed_replay = fixed_replay.resolve()
    gap_replay = gap_replay.resolve()
    for replay in (fixed_replay, gap_replay):
        try:
            replay.relative_to(root)
        except ValueError as exc:
            raise ValueError("replay exports must be generated inside the external asset root") from exc
    fixed_info = inspect_replay(fixed_replay)
    gap_info = inspect_replay(gap_replay)
    if fixed_info["vehicle_ids"] != gap_info["vehicle_ids"]:
        raise ValueError("Fixed and gap_v1 replay vehicle IDs differ")
    if fixed_info["traffic_light_ids"] != ["demo_01"] or gap_info["traffic_light_ids"] != ["demo_01"]:
        raise ValueError("replays do not contain the audited demo_01 traffic light")

    fixed_report = _json(fixed_run_report)
    adaptive_report = _json(adaptive_run_report)
    comparison = _json(comparison_report)
    validated_comparison = validate_comparison_report(comparison, dataset_id)
    expected_count = validated_comparison["inputs"]["vehicle_count"]
    for label, replay_info, run_key in (
        ("Fixed", fixed_info, "fixed"),
        ("gap_v1", gap_info, "adaptive"),
    ):
        expected_waiting = float(
            validated_comparison["runs"][run_key]["total_waiting_time_s"]
        )
        replay_waiting = replay_info["final_cumulative_waiting_time_s"]
        if require_waiting_series and not replay_info["waiting_series_available"]:
            raise ValueError(f"{label} replay has no cumulative waiting-time series")
        if replay_waiting is not None and abs(float(replay_waiting) - expected_waiting) > 1e-6:
            raise ValueError(f"{label} replay waiting time differs from the comparison")
    for label, run in (("Fixed", fixed_report), ("gap_v1", adaptive_report)):
        if run.get("validation", {}).get("passed") is not True:
            raise ValueError(f"{label} run report is not validated")
        vehicles = run.get("vehicles", {})
        if any(vehicles.get(field) != expected_count for field in ("planned", "inserted", "arrived")):
            raise ValueError(f"{label} run report is incomplete")
        diagnostics = run.get("diagnostics", {})
        if diagnostics.get("collisions") != 0 or diagnostics.get("teleports") != 0:
            raise ValueError(f"{label} run report contains collisions or teleports")
    provenance = adaptive_report.get("controller_provenance", {})
    if (
        provenance.get("selected_strategy") != "gap_v1"
        or provenance.get("active_strategy_verified_at_runtime") is not True
        or provenance.get("active_traffic_light_ids") != ["demo_01"]
    ):
        raise ValueError("adaptive run report does not prove gap_v1 activation")
    if len(fixed_info["vehicle_ids"]) != expected_count or len(gap_info["vehicle_ids"]) != expected_count:
        raise ValueError("replay observed vehicle count differs from the comparison")

    original_target = videos / "original.mp4"
    annotated_target = videos / "annotated.mp4"
    original_metadata = _prepare_video(original_video.resolve(), original_target)
    annotated_metadata = _prepare_video(annotated_video.resolve(), annotated_target)
    comparison_target = reports / "comparison_report.json"
    if comparison_target.exists():
        raise FileExistsError(f"refusing to overwrite report asset: {comparison_target}")
    shutil.copy2(comparison_report, comparison_target)

    def asset(path: Path, **metadata: Any) -> dict[str, Any]:
        return {
            "path": str(path.resolve().relative_to(root)),
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
            **metadata,
        }

    manifest = {
        "schema_version": "1.0",
        "dataset_id": dataset_id,
        "display_name": "Prerecorded AI-derived traffic experiment",
        "video": {
            "duration_s": original_metadata["duration_s"],
            "annotated_duration_s": annotated_metadata["duration_s"],
            "source_identifier": original_metadata["source_sha256"],
            "camera_orientation_verified": False,
        },
        "alignment": {
            "video_time_to_sumo_planned_departure_offset_s": 0.0,
            "video_ends_without_looping": True,
            "simulation_continues_after_video": True,
            "note": "AI event t_s and planned SUMO departures share t=0; actual insertion delays remain explicit.",
        },
        "network_geometry": {
            "scenario_id": "single_intersection",
            "api_path": "/api/simulation/network?scenario_id=single_intersection",
            "coordinate_system": fixed_info["coordinate_system"],
        },
        "input_provenance": {
            "ai_sources": validated_comparison["inputs"].get("ai_sources"),
            "route_file_sha256": validated_comparison["inputs"].get("route_file_sha256"),
            "network_sha256": validated_comparison["inputs"].get("simulation_settings", {}).get("network_sha256"),
        },
        "assets": {
            "original_video": asset(original_target, duration_s=original_metadata["duration_s"]),
            "annotated_video": asset(annotated_target, duration_s=annotated_metadata["duration_s"]),
            "fixed_replay": asset(
                fixed_replay,
                frame_count=fixed_info["frame_count"],
                waiting_series_available=fixed_info["waiting_series_available"],
            ),
            "gap_v1_replay": asset(
                gap_replay,
                frame_count=gap_info["frame_count"],
                waiting_series_available=gap_info["waiting_series_available"],
            ),
            "comparison_report": asset(comparison_target),
        },
        "replays": {
            "fixed": {
                "asset_id": "fixed_replay",
                "strategy": "fixed",
                "simulation_duration_s": fixed_info["last_simulation_time_s"],
                "waiting_time_series": {
                    "available": fixed_info["waiting_series_available"],
                    "final_cumulative_waiting_time_s": fixed_info["final_cumulative_waiting_time_s"],
                },
            },
            "gap_v1": {
                "asset_id": "gap_v1_replay",
                "strategy": "gap_v1",
                "simulation_duration_s": gap_info["last_simulation_time_s"],
                "controller_provenance": validated_comparison["adaptive_controller"],
                "waiting_time_series": {
                    "available": gap_info["waiting_series_available"],
                    "final_cumulative_waiting_time_s": gap_info["final_cumulative_waiting_time_s"],
                },
            },
        },
        "comparison": {"asset_id": "comparison_report", "validated": True},
        "limitations": [
            "The 26 vehicles initially visible at video t=0 are excluded.",
            "Camera-to-SUMO orientation is unverified.",
            "The synthetic network supports straight-through movements only.",
            "Replay metrics describe a recorded-video-derived synthetic experiment, not real-world savings.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--original-video", type=Path, required=True)
    parser.add_argument("--annotated-video", type=Path, required=True)
    parser.add_argument("--fixed-replay", type=Path, required=True)
    parser.add_argument("--gap-replay", type=Path, required=True)
    parser.add_argument("--fixed-run-report", type=Path, required=True)
    parser.add_argument("--adaptive-run-report", type=Path, required=True)
    parser.add_argument("--comparison-report", type=Path, required=True)
    parser.add_argument("--dataset-id", default="youtube_intersection_264s_v1")
    parser.add_argument(
        "--require-waiting-series",
        action="store_true",
        help="reject replay streams without a complete reconciled waiting-time series",
    )
    args = parser.parse_args()
    try:
        manifest = create_bundle(
            args.output_directory,
            original_video=args.original_video,
            annotated_video=args.annotated_video,
            fixed_replay=args.fixed_replay,
            gap_replay=args.gap_replay,
            fixed_run_report=args.fixed_run_report,
            adaptive_run_report=args.adaptive_run_report,
            comparison_report=args.comparison_report,
            dataset_id=args.dataset_id,
            require_waiting_series=args.require_waiting_series,
        )
    except (FileNotFoundError, FileExistsError, OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
