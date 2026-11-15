"""Validated allowlisted access to external AI replay assets."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MANIFEST_SCHEMA_VERSION = "1.0"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPLAY_ASSET_DIR = (
    REPOSITORY_ROOT / "assets" / "ai-traffic" / "versions" / "waiting-v1"
)
ASSET_MEDIA_TYPES = {
    "original_video": "video/mp4",
    "annotated_video": "video/mp4",
    "fixed_replay": "application/x-ndjson",
    "gap_v1_replay": "application/x-ndjson",
}


class ReplayAssetError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReplayAssetError(422, f"{label} must be an object")
    return value


def _safe_path(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ReplayAssetError(422, "asset path must be a non-empty relative path")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ReplayAssetError(422, "asset path escapes the configured replay directory") from exc
    return candidate


def validate_comparison_report(value: object, dataset_id: str) -> dict[str, Any]:
    report = _object(value, "comparison report")
    validation = _object(report.get("validation"), "comparison validation")
    inputs = _object(report.get("inputs"), "comparison inputs")
    controller = _object(report.get("adaptive_controller"), "adaptive controller")
    runs = _object(report.get("runs"), "comparison runs")
    if report.get("schema_version") != "1.0":
        raise ReplayAssetError(422, "comparison report schema is unsupported")
    if report.get("experiment") != "ai_demand_single_intersection_fixed_vs_adaptive":
        raise ReplayAssetError(422, "comparison report experiment is incompatible")
    required_validation = (
        "passed",
        "vehicle_ids_match",
        "planned_departures_and_routes_match",
        "route_file_sha256_match",
        "ai_input_sha256_match",
        "network_and_simulation_settings_match",
        "all_vehicles_completed",
    )
    if any(validation.get(field) is not True for field in required_validation):
        raise ReplayAssetError(422, "comparison report did not pass strict validation")
    if validation.get("collisions") != 0 or validation.get("teleports") != 0:
        raise ReplayAssetError(422, "comparison report contains collisions or teleports")
    vehicle_count = inputs.get("vehicle_count")
    if type(vehicle_count) is not int or vehicle_count <= 0:
        raise ReplayAssetError(422, "comparison vehicle count is invalid")
    for mode in ("fixed", "adaptive"):
        run = _object(runs.get(mode), f"{mode} comparison run")
        if run.get("vehicle_count") != vehicle_count:
            raise ReplayAssetError(422, "comparison run vehicle counts do not match")
    if (
        controller.get("selected_strategy") != "gap_v1"
        or controller.get("active_strategies") != ["gap_v1"]
        or controller.get("active_traffic_light_ids") != ["demo_01"]
        or controller.get("active_strategy_verified_at_runtime") is not True
        or controller.get("validation_errors") != []
        or not controller.get("manifest_sha256")
    ):
        raise ReplayAssetError(422, "comparison does not prove gap_v1 runtime activation")
    return {
        "schema_version": "1.0",
        "dataset_id": dataset_id,
        "validation": validation,
        "inputs": inputs,
        "runs": runs,
        "comparison": _object(report.get("comparison"), "metric comparison"),
        "adaptive_controller": {
            key: controller.get(key)
            for key in (
                "selected_strategy",
                "profile_id",
                "manifest_sha256",
                "active_traffic_light_ids",
                "active_strategies",
                "active_strategy_verified_at_runtime",
                "gap_release_decision_count",
                "validation_errors",
            )
        },
    }


@dataclass(frozen=True)
class ReplayAsset:
    asset_id: str
    path: Path
    media_type: str


class ReplayAssetStore:
    """Load one replay manifest and expose only declared, known asset IDs."""

    def __init__(self, root: Path | None = None) -> None:
        configured = root
        if configured is None:
            configured = (
                Path(value)
                if (value := os.getenv("FLOWGENCY_REPLAY_ASSET_DIR"))
                else DEFAULT_REPLAY_ASSET_DIR
            )
        self.root = configured.expanduser().resolve()

    def _root(self) -> Path:
        if not self.root.is_dir():
            raise ReplayAssetError(503, "replay asset directory is unavailable")
        return self.root

    def _load(self) -> tuple[Path, dict[str, Any]]:
        root = self._root()
        path = root / "replay_manifest.json"
        if not path.is_file():
            raise ReplayAssetError(404, "replay manifest is missing")
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReplayAssetError(422, "replay manifest is invalid JSON") from exc
        manifest = _object(manifest, "replay manifest")
        if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise ReplayAssetError(422, "replay manifest schema is unsupported")
        if not isinstance(manifest.get("dataset_id"), str) or not manifest["dataset_id"]:
            raise ReplayAssetError(422, "replay manifest dataset ID is missing")
        return root, manifest

    def asset(self, asset_id: str) -> ReplayAsset:
        if asset_id not in ASSET_MEDIA_TYPES:
            raise ReplayAssetError(404, "unknown replay asset")
        root, manifest = self._load()
        assets = _object(manifest.get("assets"), "manifest assets")
        entry = _object(assets.get(asset_id), f"asset {asset_id}")
        path = _safe_path(root, entry.get("path"))
        if not path.is_file():
            raise ReplayAssetError(404, f"replay asset {asset_id} is missing")
        return ReplayAsset(asset_id, path, ASSET_MEDIA_TYPES[asset_id])

    def public_manifest(self) -> dict[str, Any]:
        root, manifest = self._load()
        dataset_id = str(manifest["dataset_id"])
        assets = _object(manifest.get("assets"), "manifest assets")
        statuses: dict[str, Any] = {}
        for asset_id in ASSET_MEDIA_TYPES:
            entry = assets.get(asset_id)
            available = False
            metadata: dict[str, Any] = {}
            if isinstance(entry, dict):
                path = _safe_path(root, entry.get("path"))
                available = path.is_file()
                metadata = {
                    key: entry.get(key)
                    for key in (
                        "sha256",
                        "size_bytes",
                        "duration_s",
                        "frame_count",
                        "waiting_series_available",
                    )
                    if key in entry
                }
            statuses[asset_id] = {
                "available": available,
                "url": f"/api/operator/ai-traffic/assets/{asset_id}" if available else None,
                **metadata,
            }
        comparison_entry = _object(assets.get("comparison_report"), "comparison report asset")
        comparison_path = _safe_path(root, comparison_entry.get("path"))
        if not comparison_path.is_file():
            raise ReplayAssetError(404, "comparison report is missing")
        try:
            comparison_raw = json.loads(comparison_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReplayAssetError(422, "comparison report is invalid JSON") from exc
        comparison = validate_comparison_report(comparison_raw, dataset_id)
        provenance = _object(manifest.get("input_provenance"), "manifest input provenance")
        expected_provenance = {
            "ai_sources": comparison["inputs"].get("ai_sources"),
            "route_file_sha256": comparison["inputs"].get("route_file_sha256"),
            "network_sha256": comparison["inputs"].get("simulation_settings", {}).get("network_sha256"),
        }
        if provenance != expected_provenance:
            raise ReplayAssetError(422, "replay manifest and comparison dataset provenance differ")
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "dataset_id": dataset_id,
            "display_name": manifest.get("display_name"),
            "video": manifest.get("video"),
            "alignment": manifest.get("alignment"),
            "network_geometry": manifest.get("network_geometry"),
            "replays": manifest.get("replays"),
            "assets": statuses,
            "comparison": comparison,
            "limitations": manifest.get("limitations", []),
        }
