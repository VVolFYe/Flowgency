"""Second AI Traffic demo: approach_left handling, Demo 2 inputs, Demo 1 regression."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from pydantic import ValidationError

from backend.models.gates import GateEvent, GateEventInput
from backend.simulation.ai_demand import (
    generate_demand,
    initial_exclusion_limitation,
    initial_vehicles_excluded,
)
from backend.simulation.ai_input import JsonlValidationError, build_timeline


ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "scenarios" / "single_intersection" / "ai_arm_mapping.json"
SCENARIO_MAPPING = ROOT / "scenarios" / "single_intersection" / "mappings.json"
DEMO1_INPUT = ROOT / "backend" / "vision" / "samples" / "youtube_full"
DEMO2_INPUT = ROOT / "backend" / "vision" / "samples" / "youtube2"
DEMO1_MANIFEST = ROOT / "assets" / "ai-traffic" / "versions" / "waiting-v1" / "replay_manifest.json"


def counts(t_s: float, *, known: bool = True) -> dict[str, object]:
    approaches = {
        arm: {"vehicles_on_approach": 1, "entered_total": 0, "discharged_total": 0}
        for arm in ("north", "east", "south", "west")
    } if known else {}
    return {
        "schema_version": "1.0",
        "t_s": t_s,
        "approaches": approaches,
        "in_intersection": 0 if known else None,
        "model_id": "test-model",
    }


def event(kind: str, track_id: int, t_s: float, arm: str = "west", **extra: object) -> dict[str, object]:
    if kind == "approach_left":
        extra.setdefault("via", "region")  # required by the section I contract
    return {
        "schema_version": "1.0",
        "event": kind,
        "track_id": track_id,
        "arm": arm,
        "t_s": t_s,
        "frame": int(t_s * 24),
        "model_id": "test-model",
        **extra,
    }


def write(directory: Path, count_records: list[dict], event_records: list[dict]) -> tuple[Path, Path]:
    counts_path = directory / "counts.jsonl"
    events_path = directory / "events.jsonl"
    counts_path.write_text("".join(json.dumps(item) + "\n" for item in count_records), encoding="utf-8")
    events_path.write_text("".join(json.dumps(item) + "\n" for item in event_records), encoding="utf-8")
    return counts_path, events_path


class ApproachLeftTests(unittest.TestCase):
    def test_producer_and_consumer_share_the_approach_left_contract(self) -> None:
        record = event("approach_left", 41, 35.452, via="region")
        self.assertEqual(GateEventInput.model_validate(record).event, "approach_left")
        self.assertEqual(GateEvent.model_validate(record).event, "approach_left")
        for model in (GateEvent, GateEventInput):
            with self.subTest(model.__name__):
                for invalid in (
                    {key: value for key, value in record.items() if key != "via"},  # via required
                    {**record, "via": "far_gate"},  # entry-only via
                    {**record, "origin_arm": "north"},
                    {**record, "event": "approach_vanished"},
                ):
                    with self.assertRaises(ValidationError):
                        model.model_validate(invalid)

    def test_approach_left_never_creates_or_removes_demand(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            counts_path, events_path = write(
                directory,
                [counts(0.0), counts(1.0)],
                [
                    event("approach_entered", 7, 0.2),
                    event("approach_entered", 8, 0.4, arm="north"),
                    event("approach_left", 7, 1.5, via="region"),
                ],
            )
            timeline = build_timeline(counts_path, events_path, MAPPING, SCENARIO_MAPPING)
            summary = timeline.summary()
            self.assertEqual(sum(summary["new_arrivals"].values()), 2)
            self.assertEqual(summary["approach_left"]["west"], 1)
            self.assertEqual([item.track_id for item in timeline.approach_left], [7])
            demand = generate_demand(counts_path, events_path, directory / "ai.rou.xml")
            vehicles = ET.parse(directory / "ai.rou.xml").getroot().findall("vehicle")
        self.assertEqual(sorted(item.get("id") for item in vehicles), ["ai_north_8", "ai_west_7"])
        self.assertEqual(demand["vehicle_count"], 2)
        self.assertEqual(demand["approach_left_events_not_demand"]["track_ids"], [7])

    def test_inconsistent_approach_left_records_fail_loudly(self) -> None:
        cases = {
            "no earlier approach_entered": [event("approach_left", 9, 0.5)],
            "entered on arm": [
                event("approach_entered", 9, 0.2, arm="north"),
                event("approach_left", 9, 0.5, arm="west"),
            ],
            "duplicate approach_left": [
                event("approach_entered", 9, 0.2),
                event("approach_left", 9, 0.5),
                event("approach_left", 9, 0.6),
            ],
            "outside the recording": [
                event("approach_entered", 9, 0.2),
                event("approach_left", 9, 5.0),
            ],
        }
        for message, records in cases.items():
            with self.subTest(message), tempfile.TemporaryDirectory() as temporary:
                counts_path, events_path = write(Path(temporary), [counts(0.0), counts(1.0)], records)
                with self.assertRaisesRegex(JsonlValidationError, message):
                    build_timeline(counts_path, events_path, MAPPING, SCENARIO_MAPPING)

    def test_warm_up_line_is_the_starting_offset_without_any_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            counts_path, events_path = write(
                directory,
                [counts(0.0, known=False), counts(1.0)],
                [event("approach_entered", 1, 1.3)],
            )
            summary = generate_demand(counts_path, events_path, directory / "warm.rou.xml")
        initial = summary["initial_observed_vehicles_not_inserted"]
        self.assertEqual((initial["observed_at_t_s"], initial["total"]), (1.0, 4))
        self.assertNotIn("status", initial)
        self.assertEqual(summary["vehicle_count"], 1)
        self.assertEqual(
            initial_exclusion_limitation(summary, "The {count} vehicles seen at video {at}."),
            "The 4 vehicles seen at video t=1s (first counts line with every arm known).",
        )

    def test_no_complete_line_requires_explicit_opt_in_and_stays_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            counts_path, events_path = write(
                directory,
                [counts(0.0, known=False), counts(1.0, known=False)],
                [event("approach_entered", 1, 0.3)],
            )
            with self.assertRaisesRegex(JsonlValidationError, "vehicle count known for every arm"):
                generate_demand(counts_path, events_path, directory / "strict.rou.xml")
            self.assertFalse((directory / "strict.rou.xml").exists())
            summary = generate_demand(
                counts_path,
                events_path,
                directory / "opt-in.rou.xml",
                allow_unknown_initial_observations=True,
            )
            vehicles = ET.parse(directory / "opt-in.rou.xml").getroot().findall("vehicle")
        initial = summary["initial_observed_vehicles_not_inserted"]
        self.assertIsNone(initial["total"])
        self.assertIsNone(initial["observed_at_t_s"])
        self.assertEqual(initial["status"], "unknown_no_complete_observation")
        self.assertEqual(set(initial["by_camera_arm"].values()), {None})
        self.assertEqual([item.get("id") for item in vehicles], ["ai_west_1"])  # arrivals only, none invented
        self.assertIsNone(initial_vehicles_excluded(summary))
        self.assertIn("count unknown", initial_exclusion_limitation(summary, "The {count} vehicles at {at}"))
        legacy = {"initial_observed_vehicles_not_inserted": {"total": None, "status": "unknown_at_t0"}}
        self.assertEqual(  # summaries written before the warm-up rule keep their original, accurate text
            initial_exclusion_limitation(legacy, "The {count} vehicles at {at}"),
            "Approach vehicles present at video t=0 were not observed (count unknown) and are not inserted.",
        )


@unittest.skipUnless((DEMO2_INPUT / "events.jsonl").is_file(), "Demo 2 AI inputs are unavailable")
class Demo2InputTests(unittest.TestCase):
    def test_demo2_files_match_independent_counts(self) -> None:
        events = [
            json.loads(line)
            for line in (DEMO2_INPUT / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        count_lines = [
            line for line in (DEMO2_INPUT / "counts.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(count_lines), 156)
        self.assertEqual(len(events), 403)
        kinds = Counter(item["event"] for item in events)
        self.assertEqual(kinds["approach_entered"], 132)
        self.assertEqual(kinds["approach_left"], 3)
        self.assertEqual(
            Counter(item["arm"] for item in events if item["event"] == "approach_entered"),
            Counter({"north": 49, "east": 21, "south": 44, "west": 18}),
        )

    def test_demo2_timeline_and_demand(self) -> None:
        timeline = build_timeline(
            DEMO2_INPUT / "counts.jsonl", DEMO2_INPUT / "events.jsonl", MAPPING, SCENARIO_MAPPING
        )
        summary = timeline.summary()
        self.assertEqual(summary["observation_count"], 156)
        self.assertEqual(summary["recording_end_s"], 156.0)
        self.assertEqual(summary["new_arrivals"], {"north": 49, "east": 21, "south": 44, "west": 18})
        self.assertEqual(summary["approach_left"], {"north": 0, "east": 0, "south": 0, "west": 3})
        # Lines t=0..2 are the vision warm-up (unknown); the starting offset is the t=3 line.
        self.assertIsNone(timeline.points[0].approaches["north"].observed_vehicles)
        self.assertEqual(summary["initial_observation_t_s"], 3.0)
        self.assertEqual(summary["initial_observed_vehicles"], {"north": 3, "east": 3, "south": 4, "west": 6})
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            default = generate_demand(
                DEMO2_INPUT / "counts.jsonl", DEMO2_INPUT / "events.jsonl", directory / "default.rou.xml"
            )
            demand = generate_demand(
                DEMO2_INPUT / "counts.jsonl",
                DEMO2_INPUT / "events.jsonl",
                directory / "demo2.rou.xml",
                allow_unknown_initial_observations=True,
            )
            vehicles = ET.parse(directory / "demo2.rou.xml").getroot().findall("vehicle")
            self.assertEqual((directory / "default.rou.xml").read_bytes(), (directory / "demo2.rou.xml").read_bytes())
        self.assertEqual(default, demand)  # the opt-in changes nothing when a complete line exists
        self.assertEqual(demand["initial_observed_vehicles_not_inserted"]["observed_at_t_s"], 3.0)
        self.assertEqual(demand["initial_observed_vehicles_not_inserted"]["total"], 16)
        ids = [item.get("id") for item in vehicles]
        self.assertEqual(len(ids), 132)
        self.assertEqual(len(set(ids)), 132)
        self.assertEqual(demand["arrivals_by_camera_arm"], {"north": 49, "east": 21, "south": 44, "west": 18})
        self.assertEqual(demand["approach_left_events_not_demand"]["track_ids"], [41, 10, 550])
        for track in (41, 10, 550):
            self.assertEqual(sum(vehicle_id.endswith(f"_{track}") for vehicle_id in ids), 1)


@unittest.skipUnless(
    (DEMO1_INPUT / "events.jsonl").is_file() and DEMO1_MANIFEST.is_file(),
    "Demo 1 inputs or bundle are unavailable",
)
class Demo1RegressionTests(unittest.TestCase):
    def test_demo1_demand_is_byte_identical_to_its_validated_bundle(self) -> None:
        manifest = json.loads(DEMO1_MANIFEST.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "ai_demand.rou.xml"
            summary = generate_demand(DEMO1_INPUT / "counts.jsonl", DEMO1_INPUT / "events.jsonl", output)
            from backend.simulation.ai_demand import _sha256

            route_sha = _sha256(output)
        self.assertEqual(route_sha, manifest["input_provenance"]["route_file_sha256"])
        self.assertEqual(summary["sources"], manifest["input_provenance"]["ai_sources"])
        self.assertEqual(summary["vehicle_count"], 325)
        self.assertEqual(initial_vehicles_excluded(summary), 26)
        self.assertEqual(summary["initial_observed_vehicles_not_inserted"]["observed_at_t_s"], 0.0)
        self.assertNotIn("status", summary["initial_observed_vehicles_not_inserted"])
        self.assertEqual(
            initial_exclusion_limitation(summary, "The {count} vehicles already observed at video {at} are excluded."),
            "The 26 vehicles already observed at video t=0 are excluded.",
        )
        self.assertNotIn("approach_left_events_not_demand", summary)
        self.assertIn(
            "The 26 initially observed approach vehicles are metadata only and are not inserted.",
            summary["assumptions"],
        )


@unittest.skipUnless(
    shutil.which("sumo") and (DEMO2_INPUT / "events.jsonl").is_file(),
    "SUMO or Demo 2 inputs are unavailable",
)
class Demo2SumoExperimentTests(unittest.TestCase):
    """Real SUMO runs: identical demand, completion, safety and waiting reconciliation."""

    def test_fixed_and_gap_v1_on_demo2_demand(self) -> None:
        from backend.api.replay_assets import validate_comparison_report
        from backend.simulation.ai_adaptive_run import run_adaptive_experiment
        from backend.simulation.ai_compare import compare_experiments
        from backend.simulation.ai_fixed_run import run_fixed_experiment
        from backend.simulation.replay import inspect_replay

        common = {
            "counts_path": DEMO2_INPUT / "counts.jsonl",
            "events_path": DEMO2_INPUT / "events.jsonl",
            "wall_timeout_s": 120.0,
            "allow_unknown_initial_observations": True,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixed = run_fixed_experiment(
                output_directory=root / "fixed",
                replay_output_path=root / "fixed.jsonl",
                **common,
            )
            gap = run_adaptive_experiment(
                output_directory=root / "gap_v1",
                replay_output_path=root / "gap_v1.jsonl",
                adaptive_strategy="gap_v1",
                fixed_demand_route=root / "fixed" / "ai_demand.rou.xml",
                **common,
            )
            report, per_vehicle = compare_experiments(root / "fixed", root / "gap_v1", adaptive_strategy="gap_v1")
            fixed_info = inspect_replay(root / "fixed.jsonl")
            gap_info = inspect_replay(root / "gap_v1.jsonl")
            first_frames = [
                json.loads((root / name).read_text(encoding="utf-8").splitlines()[0])
                for name in ("fixed.jsonl", "gap_v1.jsonl")
            ]

        for run in (fixed, gap):
            self.assertTrue(run["validation"]["passed"], run["validation"]["errors"])
            self.assertEqual(run["vehicles"]["planned"], 132)
            self.assertEqual(run["vehicles"]["arrived"], 132)
            self.assertEqual(run["diagnostics"]["collisions"], 0)
            self.assertEqual(run["diagnostics"]["teleports"], 0)
            self.assertTrue(run["replay_waiting_time_reconciliation"]["matches"])
            self.assertTrue(run["limitations"][0].startswith("The 16 vehicles already observed at video t=3s"))
        self.assertEqual(
            gap["fixed_baseline_demand_comparison"],
            {**gap["fixed_baseline_demand_comparison"], "ids_match": True, "planned_departures_match": True, "route_file_sha256_match": True},
        )
        self.assertEqual(gap["signal_safety"]["errors"], [])
        self.assertEqual(gap["controller_provenance"]["active_strategies"], ["gap_v1"])
        self.assertTrue(gap["controller_provenance"]["active_strategy_verified_at_runtime"])
        self.assertEqual(validate_comparison_report(report, "demo2")["inputs"]["vehicle_count"], 132)
        self.assertEqual(len(per_vehicle), 132)
        self.assertEqual(fixed_info["vehicle_ids"], gap_info["vehicle_ids"])
        for frame in first_frames:
            self.assertEqual(frame["metrics"]["cumulative_waiting_time_s"], 0.0)
        self.assertEqual(fixed_info["final_cumulative_waiting_time_s"], report["runs"]["fixed"]["total_waiting_time_s"])
        self.assertEqual(gap_info["final_cumulative_waiting_time_s"], report["runs"]["adaptive"]["total_waiting_time_s"])


DEMO2_BUNDLE = ROOT / "assets" / "ai-traffic" / "versions" / "demo2-v1"


@unittest.skipUnless((DEMO2_BUNDLE / "replay_manifest.json").is_file(), "Demo 2 bundle is not generated")
class Demo2BundleTests(unittest.TestCase):
    """Read-only checks of the generated Demo 2 bundle (skipped until it exists)."""

    def test_bundle_is_valid_annotated_only_and_independent_of_demo1(self) -> None:
        import hashlib

        from backend.api.replay_assets import ReplayDatasetRegistry
        from backend.simulation.replay import inspect_replay

        def sha(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()

        manifest = json.loads((DEMO2_BUNDLE / "replay_manifest.json").read_text(encoding="utf-8"))
        demo1 = json.loads(DEMO1_MANIFEST.read_text(encoding="utf-8"))
        for entry in manifest["assets"].values():
            path = DEMO2_BUNDLE / entry["path"]
            self.assertEqual(path.stat().st_size, entry["size_bytes"], entry["path"])
            self.assertEqual(sha(path), entry["sha256"], entry["path"])
        self.assertNotIn("original_video", manifest["assets"])
        self.assertEqual(manifest["video"]["source_kind"], "annotated_only")
        self.assertTrue({e["sha256"] for e in manifest["assets"].values()}.isdisjoint(
            {e["sha256"] for e in demo1["assets"].values()}
        ))
        self.assertNotEqual(manifest["dataset_id"], demo1["dataset_id"])
        if (DEMO2_INPUT / "counts.jsonl").is_file():
            self.assertEqual(manifest["input_provenance"]["ai_sources"], {
                "counts_sha256": sha(DEMO2_INPUT / "counts.jsonl"),
                "events_sha256": sha(DEMO2_INPUT / "events.jsonl"),
            })
        served = ReplayDatasetRegistry().public_manifest("demo2")
        comparison = served["comparison"]
        for mode, run in (("fixed", "fixed"), ("gap_v1", "adaptive")):
            info = inspect_replay(DEMO2_BUNDLE / manifest["assets"][f"{mode}_replay"]["path"])
            self.assertTrue(info["waiting_series_available"])
            self.assertEqual(info["final_cumulative_waiting_time_s"], comparison["runs"][run]["total_waiting_time_s"])
            self.assertEqual(len(info["vehicle_ids"]), comparison["inputs"]["vehicle_count"])
            self.assertEqual(info["frame_count"], manifest["assets"][f"{mode}_replay"]["frame_count"])
        self.assertTrue(comparison["adaptive_controller"]["active_strategy_verified_at_runtime"])
        self.assertEqual((comparison["validation"]["collisions"], comparison["validation"]["teleports"]), (0, 0))


class AnnotatedOnlyBundleTests(unittest.TestCase):
    """create_bundle must omit, never fabricate, the original video."""

    def test_annotated_only_manifest(self) -> None:
        from backend.simulation import ai_replay_bundle

        def fake_prepare(source: Path, target: Path) -> dict[str, object]:
            target.write_bytes(source.read_bytes())
            return {
                "duration_s": 156.031031, "codec": "h264", "width": 1280, "height": 720,
                "pixel_format": "yuv420p", "conversion": "copied_existing_h264",
                "source_sha256": "annotated-source", "sha256": "x", "size_bytes": target.stat().st_size,
            }

        report = {
            "schema_version": "1.0",
            "experiment": "ai_demand_single_intersection_fixed_vs_adaptive",
            "validation": {
                "passed": True, "vehicle_ids_match": True, "planned_departures_and_routes_match": True,
                "route_file_sha256_match": True, "ai_input_sha256_match": True,
                "network_and_simulation_settings_match": True, "all_vehicles_completed": True,
                "collisions": 0, "teleports": 0,
            },
            "inputs": {
                "vehicle_count": 1, "ai_sources": {"counts_sha256": "c", "events_sha256": "e"},
                "route_file_sha256": "r", "simulation_settings": {"network_sha256": "n"},
            },
            "runs": {
                "fixed": {"vehicle_count": 1, "total_waiting_time_s": 1.0},
                "adaptive": {"vehicle_count": 1, "total_waiting_time_s": 1.0},
            },
            "comparison": {},
            "adaptive_controller": {
                "selected_strategy": "gap_v1", "active_strategies": ["gap_v1"],
                "active_traffic_light_ids": ["demo_01"], "active_strategy_verified_at_runtime": True,
                "validation_errors": [], "manifest_sha256": "m",
            },
        }
        run = {
            "validation": {"passed": True},
            "vehicles": {"planned": 1, "inserted": 1, "arrived": 1},
            "diagnostics": {"collisions": 0, "teleports": 0},
            "demand": {
                "initial_observed_vehicles_not_inserted": {
                    "observed_at_t_s": None, "total": None, "status": "unknown_no_complete_observation",
                },
                "approach_left_events_not_demand": {"count": 3},
            },
            "controller_provenance": {
                "selected_strategy": "gap_v1", "active_strategy_verified_at_runtime": True,
                "active_traffic_light_ids": ["demo_01"],
            },
        }
        info = {
            "vehicle_ids": ["ai_north_1"], "traffic_light_ids": ["demo_01"], "frame_count": 2,
            "last_simulation_time_s": 1.0, "waiting_series_available": True,
            "final_cumulative_waiting_time_s": 1.0, "coordinate_system": "synthetic_cartesian_metres",
        }
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as temporary:
            root = Path(temporary)
            (root / "replays").mkdir()
            for name in ("fixed.jsonl", "gap.jsonl"):
                (root / "replays" / name).write_text("{}\n", encoding="utf-8")
            inputs = root / "inputs"
            inputs.mkdir()
            (inputs / "annotated.mp4").write_bytes(b"annotated")
            for name, value in (("fixed.json", run), ("gap.json", run), ("comparison.json", report)):
                (inputs / name).write_text(json.dumps(value), encoding="utf-8")
            with (
                patch.object(ai_replay_bundle, "_prepare_video", side_effect=fake_prepare) as prepare,
                patch.object(ai_replay_bundle, "inspect_replay", return_value=info),
            ):
                with self.assertRaisesRegex(ValueError, "must not be labelled as the original"):
                    ai_replay_bundle.create_bundle(
                        root, original_video=inputs / "annotated.mp4", annotated_video=inputs / "annotated.mp4",
                        fixed_replay=root / "replays" / "fixed.jsonl", gap_replay=root / "replays" / "gap.jsonl",
                        fixed_run_report=inputs / "fixed.json", adaptive_run_report=inputs / "gap.json",
                        comparison_report=inputs / "comparison.json", dataset_id="demo2-test",
                    )
                manifest_path = ai_replay_bundle.create_bundle(
                    root, original_video=None, annotated_video=inputs / "annotated.mp4",
                    fixed_replay=root / "replays" / "fixed.jsonl", gap_replay=root / "replays" / "gap.jsonl",
                    fixed_run_report=inputs / "fixed.json", adaptive_run_report=inputs / "gap.json",
                    comparison_report=inputs / "comparison.json", dataset_id="demo2-test",
                    display_name="Demo 2",
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertFalse((root / "videos" / "original.mp4").exists())
        self.assertEqual(prepare.call_count, 1)
        self.assertNotIn("original_video", manifest["assets"])
        self.assertIsNone(manifest["video"]["duration_s"])
        self.assertEqual(manifest["video"]["annotated_duration_s"], 156.031031)
        self.assertEqual(manifest["video"]["source_kind"], "annotated_only")
        self.assertFalse(manifest["video"]["original_video_available"])
        self.assertEqual(manifest["display_name"], "Demo 2")
        joined = " ".join(manifest["limitations"])
        self.assertIn("count unknown", joined)
        self.assertIn("Only the AI-annotated video was provided", joined)
        self.assertIn("3 approach_left events", joined)
        self.assertNotIn("26", joined)


if __name__ == "__main__":
    unittest.main()
