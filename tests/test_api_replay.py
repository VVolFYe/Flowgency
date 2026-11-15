from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api.app import create_app
from backend.api.auth import Auth0TokenVerifier
from backend.api.replay_assets import (
    DEFAULT_DEMO2_REPLAY_ASSET_DIR,
    DEFAULT_REPLAY_ASSET_DIR,
    ReplayAssetError,
    ReplayAssetStore,
    ReplayDatasetRegistry,
    validate_comparison_report,
)
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
    dataset_id: str = "dataset-v1",
    annotated_only: bool = False,
) -> ReplayAssetStore:
    (root / "videos").mkdir()
    (root / "replays").mkdir()
    (root / "reports").mkdir()
    if not annotated_only:
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
        "dataset_id": dataset_id,
        "display_name": "Dataset",
        "video": (
            {"duration_s": None, "annotated_duration_s": 156.0, "source_kind": "annotated_only", "original_video_available": False}
            if annotated_only
            else {"duration_s": 264}
        ),
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
            **({} if annotated_only else {
                "original_video": {"path": "../outside.mp4" if traversal else "videos/original.mp4"},
            }),
            "annotated_video": {"path": "videos/annotated.mp4"},
            "fixed_replay": {"path": "replays/fixed.jsonl"},
            "gap_v1_replay": {"path": "replays/gap.jsonl"},
            "comparison_report": {"path": "reports/comparison.json"},
        },
    }
    (root / "replay_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return ReplayAssetStore(root)


def replay_app(store: ReplayAssetStore, datasets: ReplayDatasetRegistry | None = None):
    verifier = Auth0TokenVerifier(DOMAIN, AUDIENCE, StaticJwksClient())
    return create_app(
        service=StubSimulationService(),
        auth0_verifier=verifier,
        replay_asset_store=store,
        replay_datasets=datasets,
    )


OPERATOR = ["simulation:read", "analytics:read", "simulation:control"]


class ReplayAssetTests(unittest.TestCase):
    def test_default_bundle_is_discovered_independently_of_working_directory(self) -> None:
        with patch.dict(os.environ, {}, clear=True), tempfile.TemporaryDirectory() as working:
            previous = Path.cwd()
            try:
                os.chdir(working)
                store = ReplayAssetStore()
                manifest = store.public_manifest()
            finally:
                os.chdir(previous)
        self.assertEqual(store.root, DEFAULT_REPLAY_ASSET_DIR.resolve())
        self.assertEqual(manifest["dataset_id"], "youtube_intersection_264s_v1")
        self.assertTrue(all(asset["available"] for asset in manifest["assets"].values()))

    def test_environment_override_takes_precedence_over_default_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            override = Path(temporary)
            write_store(override)
            with patch.dict(
                os.environ,
                {"FLOWGENCY_REPLAY_ASSET_DIR": str(override)},
                clear=True,
            ):
                store = ReplayAssetStore()
                self.assertEqual(store.root, override.resolve())
                self.assertEqual(store.public_manifest()["dataset_id"], "dataset-v1")

    def test_missing_default_bundle_returns_service_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing"
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("backend.api.replay_assets.DEFAULT_REPLAY_ASSET_DIR", missing),
            ):
                with self.assertRaisesRegex(ReplayAssetError, "unavailable") as raised:
                    ReplayAssetStore().public_manifest()
        self.assertEqual(raised.exception.status_code, 503)

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


class ReplayDatasetTests(unittest.TestCase):
    def two_datasets(self, root: Path, *, demo2: bool = True) -> tuple[ReplayAssetStore, ReplayDatasetRegistry]:
        (root / "one").mkdir()
        demo1 = write_store(root / "one", dataset_id="first-v1")
        if demo2:
            (root / "two").mkdir()
            write_store(root / "two", dataset_id="second-v1", annotated_only=True)
        return demo1, ReplayDatasetRegistry({"demo1": root / "one", "demo2": root / "two"})

    def test_default_registry_discovers_both_bundles_relative_to_repository(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            registry = ReplayDatasetRegistry()
        self.assertEqual(registry.dataset_ids, ("demo1", "demo2"))
        self.assertEqual(registry.dataset("demo1").store.root, DEFAULT_REPLAY_ASSET_DIR.resolve())
        self.assertEqual(registry.dataset("demo2").store.root, DEFAULT_DEMO2_REPLAY_ASSET_DIR.resolve())
        listing = registry.list_datasets()
        self.assertEqual(listing["default_dataset_id"], "demo1")
        self.assertTrue(listing["datasets"][0]["default"])
        self.assertNotIn(str(DEFAULT_REPLAY_ASSET_DIR), json.dumps(listing))

    def test_existing_demo1_override_still_applies_to_dataset_demo1(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            write_store(Path(temporary))
            with patch.dict(os.environ, {"FLOWGENCY_REPLAY_ASSET_DIR": temporary}, clear=True):
                registry = ReplayDatasetRegistry()
                self.assertEqual(registry.public_manifest("demo1")["dataset_id"], "dataset-v1")

    def test_unknown_dataset_ids_are_rejected_without_path_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, registry = self.two_datasets(Path(temporary))
            for unknown in ("demo3", "../one", "one", "", "DEMO1", "demo1/../demo2"):
                with self.subTest(unknown), self.assertRaises(ReplayAssetError) as raised:
                    registry.public_manifest(unknown)
                self.assertEqual(raised.exception.status_code, 404)
        with self.assertRaisesRegex(ValueError, "unknown replay dataset"):
            ReplayDatasetRegistry({"demo3": Path("/")})

    def test_datasets_load_independently_with_scoped_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, registry = self.two_datasets(Path(temporary))
            first = registry.public_manifest("demo1")
            second = registry.public_manifest("demo2")
        self.assertEqual((first["selection_id"], first["dataset_id"]), ("demo1", "first-v1"))
        self.assertEqual((second["selection_id"], second["dataset_id"]), ("demo2", "second-v1"))
        self.assertEqual(first["assets"]["fixed_replay"]["url"], "/api/operator/ai-traffic/datasets/demo1/assets/fixed_replay")
        self.assertEqual(second["assets"]["fixed_replay"]["url"], "/api/operator/ai-traffic/datasets/demo2/assets/fixed_replay")

    def test_annotated_only_dataset_exposes_no_original_video(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, registry = self.two_datasets(Path(temporary))
            manifest = registry.public_manifest("demo2")
            with self.assertRaisesRegex(ReplayAssetError, "original_video") as raised:
                registry.asset("demo2", "original_video")
            listing = {item["dataset_id"]: item for item in registry.list_datasets()["datasets"]}
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(manifest["assets"]["original_video"], {"available": False, "url": None})
        self.assertTrue(manifest["assets"]["annotated_video"]["available"])
        self.assertIsNone(manifest["video"]["duration_s"])
        self.assertEqual(listing["demo2"]["video_sources"], ["annotated_video"])
        self.assertEqual(listing["demo1"]["video_sources"], ["original_video", "annotated_video"])

    def test_missing_demo2_bundle_is_reported_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, registry = self.two_datasets(Path(temporary), demo2=False)
            with self.assertRaisesRegex(ReplayAssetError, "unavailable") as raised:
                registry.public_manifest("demo2")
            listing = {item["dataset_id"]: item for item in registry.list_datasets()["datasets"]}
        self.assertEqual(raised.exception.status_code, 503)
        self.assertTrue(listing["demo1"]["available"])
        self.assertFalse(listing["demo2"]["available"])
        self.assertEqual(listing["demo2"]["video_sources"], [])

    def test_demo1_bundle_is_never_served_as_demo2(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_store(root)
            same_root = ReplayDatasetRegistry({"demo1": root, "demo2": root})
            with self.assertRaisesRegex(ReplayAssetError, "Demo 1 bundle directory"):
                same_root.public_manifest("demo2")
            with self.assertRaisesRegex(ReplayAssetError, "Demo 1 bundle directory"):
                same_root.asset("demo2", "annotated_video")
            copy = root / "copy"
            copy.mkdir()
            write_store(copy)
            duplicate = ReplayDatasetRegistry({"demo1": root, "demo2": copy})
            with self.assertRaisesRegex(ReplayAssetError, "duplicates the Demo 1"):
                duplicate.public_manifest("demo2")

    def test_dataset_api_authorization_ranges_and_legacy_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            demo1, registry = self.two_datasets(Path(temporary))
            app = replay_app(demo1, registry)
            paths = (
                "/api/ai-traffic/datasets",
                "/api/ai-traffic/datasets/demo2/manifest",
                "/api/ai-traffic/datasets/demo2/assets/annotated_video",
            )
            partial = {"Authorization": f"Bearer {make_token(['simulation:read', 'analytics:read'])}"}
            for path in paths:
                self.assertEqual(request(app, "GET", path).status_code, 401)
                self.assertEqual(request(app, "GET", path, headers=partial).status_code, 403)
            headers = {"Authorization": f"Bearer {make_token(OPERATOR)}"}
            listing = request(app, "GET", "/api/ai-traffic/datasets", headers=headers).json()
            self.assertEqual(listing["default_dataset_id"], "demo1")
            self.assertEqual([item["available"] for item in listing["datasets"]], [True, True])
            manifest = request(app, "GET", "/api/ai-traffic/datasets/demo2/manifest", headers=headers)
            self.assertEqual(manifest.status_code, 200)
            self.assertNotIn("path", json.dumps(manifest.json()))
            video = request(
                app, "GET", "/api/ai-traffic/datasets/demo1/assets/original_video",
                headers={**headers, "Range": "bytes=2-5"},
            )
            self.assertEqual(video.status_code, 206)
            self.assertEqual(video.content, b"2345")
            self.assertEqual(video.headers["content-range"], "bytes 2-5/10")
            annotated = request(
                app, "GET", "/api/ai-traffic/datasets/demo2/assets/annotated_video",
                headers={**headers, "Range": "bytes=0-3"},
            )
            self.assertEqual((annotated.status_code, annotated.content), (206, b"anno"))
            for path in (
                "/api/ai-traffic/datasets/demo3/manifest",
                "/api/ai-traffic/datasets/demo2/assets/secret",
                "/api/ai-traffic/datasets/..%2Fone/manifest",
            ):
                self.assertEqual(request(app, "GET", path, headers=headers).status_code, 404, path)
            legacy = request(app, "GET", "/api/ai-traffic/manifest", headers=headers).json()
            self.assertEqual(legacy["dataset_id"], "first-v1")
            self.assertNotIn("selection_id", legacy)
            self.assertEqual(legacy["assets"]["fixed_replay"]["url"], "/api/operator/ai-traffic/assets/fixed_replay")

    def test_injected_demo1_store_is_reused_by_the_dataset_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            demo1 = write_store(Path(temporary))
            app = replay_app(demo1)
            headers = {"Authorization": f"Bearer {make_token(OPERATOR)}"}
            scoped = request(app, "GET", "/api/ai-traffic/datasets/demo1/manifest", headers=headers).json()
        self.assertEqual(scoped["dataset_id"], "dataset-v1")


if __name__ == "__main__":
    unittest.main()
