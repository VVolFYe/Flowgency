from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.api.app import create_app
from backend.api.auth import Auth0TokenVerifier
from backend.api.replay_assets import ReplayAssetError, ReplayAssetStore, validate_comparison_report
from tests.test_api_auth import AUDIENCE, DOMAIN, StaticJwksClient, StubSimulationService, make_token, request


def comparison_report() -> dict:
    metrics = {"vehicle_count": 1, "total_waiting_time_s": 3.0}
    return {
        "schema_version": "1.0",
        "experiment": "ai_demand_single_intersection_fixed_vs_adaptive",
        "validation": {
            "passed": True,
            "vehicle_ids_match": True,
            "planned_departures_and_routes_match": True,
            "route_file_sha256_match": True,
            "ai_input_sha256_match": True,
            "network_and_simulation_settings_match": True,
            "all_vehicles_completed": True,
            "collisions": 0,
            "teleports": 0,
        },
        "inputs": {
            "vehicle_count": 1,
            "ai_sources": {"counts_sha256": "counts", "events_sha256": "events"},
            "route_file_sha256": "route",
            "simulation_settings": {"network_sha256": "network"},
        },
        "runs": {"fixed": metrics, "adaptive": metrics},
        "comparison": {"total_waiting_time_s": {"fixed": 3, "adaptive": 2}},
        "adaptive_controller": {
            "selected_strategy": "gap_v1",
            "profile_id": "single_intersection_gap_v1_experimental",
            "manifest_sha256": "manifest",
            "active_traffic_light_ids": ["demo_01"],
            "active_strategies": ["gap_v1"],
            "active_strategy_verified_at_runtime": True,
            "gap_release_decision_count": 1,
            "validation_errors": [],
        },
    }


def write_store(
    root: Path,
    *,
    traversal: bool = False,
    invalid_comparison: bool = False,
    mismatched_provenance: bool = False,
) -> ReplayAssetStore:
    (root / "videos").mkdir()
    (root / "replays").mkdir()
    (root / "reports").mkdir()
    (root / "videos" / "original.mp4").write_bytes(b"0123456789")
    (root / "videos" / "annotated.mp4").write_bytes(b"annotated")
    (root / "replays" / "fixed.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "replays" / "gap.jsonl").write_text("{}\n", encoding="utf-8")
    report = comparison_report()
    if invalid_comparison:
        report["validation"]["passed"] = False
    (root / "reports" / "comparison.json").write_text(json.dumps(report), encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "dataset_id": "dataset-v1",
        "display_name": "Dataset",
        "video": {"duration_s": 264},
        "alignment": {"video_time_to_sumo_planned_departure_offset_s": 0},
        "network_geometry": {"scenario_id": "single_intersection"},
        "replays": {},
        "input_provenance": {
            "ai_sources": (
                {"counts_sha256": "different", "events_sha256": "events"}
                if mismatched_provenance
                else report["inputs"]["ai_sources"]
            ),
            "route_file_sha256": "route",
            "network_sha256": "network",
        },
        "assets": {
            "original_video": {"path": "../outside.mp4" if traversal else "videos/original.mp4"},
            "annotated_video": {"path": "videos/annotated.mp4"},
            "fixed_replay": {"path": "replays/fixed.jsonl"},
            "gap_v1_replay": {"path": "replays/gap.jsonl"},
            "comparison_report": {"path": "reports/comparison.json"},
        },
    }
    (root / "replay_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return ReplayAssetStore(root)


def replay_app(store: ReplayAssetStore):
    verifier = Auth0TokenVerifier(DOMAIN, AUDIENCE, StaticJwksClient())
    return create_app(
        service=StubSimulationService(),
        auth0_verifier=verifier,
        replay_asset_store=store,
    )


class ReplayAssetTests(unittest.TestCase):
    def test_comparison_requires_verified_gap_controller(self) -> None:
        report = comparison_report()
        validated = validate_comparison_report(report, "dataset-v1")
        self.assertEqual(validated["adaptive_controller"]["selected_strategy"], "gap_v1")
        report["adaptive_controller"]["selected_strategy"] = "legacy"
        with self.assertRaisesRegex(ReplayAssetError, "gap_v1"):
            validate_comparison_report(report, "dataset-v1")

    def test_path_traversal_and_unknown_assets_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = write_store(Path(temporary), traversal=True)
            with self.assertRaisesRegex(ReplayAssetError, "escapes"):
                store.asset("original_video")
            with self.assertRaisesRegex(ReplayAssetError, "unknown"):
                store.asset("secret")

    def test_missing_and_invalid_manifest_handling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ReplayAssetStore(Path(temporary))
            with self.assertRaisesRegex(ReplayAssetError, "missing"):
                store.public_manifest()
        with tempfile.TemporaryDirectory() as temporary:
            store = write_store(Path(temporary), invalid_comparison=True)
            with self.assertRaisesRegex(ReplayAssetError, "strict validation"):
                store.public_manifest()
        with tempfile.TemporaryDirectory() as temporary:
            store = write_store(Path(temporary), mismatched_provenance=True)
            with self.assertRaisesRegex(ReplayAssetError, "provenance differ"):
                store.public_manifest()

    def test_api_requires_all_operator_permissions_and_supports_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = replay_app(write_store(Path(temporary)))
            self.assertEqual(request(app, "GET", "/api/ai-traffic/manifest").status_code, 401)
            partial = make_token(["simulation:read", "analytics:read"])
            self.assertEqual(request(app, "GET", "/api/ai-traffic/manifest", headers={"Authorization": f"Bearer {partial}"}).status_code, 403)
            token = make_token(["simulation:read", "analytics:read", "simulation:control"])
            headers = {"Authorization": f"Bearer {token}"}
            manifest = request(app, "GET", "/api/ai-traffic/manifest", headers=headers)
            self.assertEqual(manifest.status_code, 200)
            self.assertNotIn("path", json.dumps(manifest.json()))
            video = request(app, "GET", "/api/ai-traffic/assets/original_video", headers={**headers, "Range": "bytes=2-5"})
            self.assertEqual(video.status_code, 206)
            self.assertEqual(video.content, b"2345")
            self.assertEqual(video.headers["content-range"], "bytes 2-5/10")


if __name__ == "__main__":
    unittest.main()
