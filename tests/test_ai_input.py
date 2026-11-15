"""Focused tests for prerecorded AI gate JSONL import."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from backend.models.gates import (
    GateCounts,
    GateCountsInput,
    GateEvent,
    GateEventInput,
)
from backend.simulation.ai_input import JsonlValidationError, build_timeline


ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "scenarios" / "single_intersection" / "ai_arm_mapping.json"
SCENARIO_MAPPING = ROOT / "scenarios" / "single_intersection" / "mappings.json"
LOCAL_SAMPLE = Path.home() / "flowgency_ai_samples"


def count_record(t_s: float, *, extra: bool = False) -> dict[str, object]:
    approaches: dict[str, object] = {}
    for arm, vehicles in (("north", 5), ("east", 3), ("south", 4), ("west", 14)):
        value: dict[str, object] = {
            "vehicles_on_approach": vehicles,
            "entered_total": 0,
            "discharged_total": 0,
        }
        if extra:
            value["future_confidence"] = 0.9
        approaches[arm] = value
    result: dict[str, object] = {
        "schema_version": "1.0",
        "t_s": t_s,
        "approaches": approaches,
        "in_intersection": 5,
        "model_id": "test-model",
    }
    if extra:
        result["emergency_metadata"] = {"status": "future"}
    return result


def event_record(track_id: int, t_s: float, arm: str = "east", **extra: object) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "event": "approach_entered",
        "track_id": track_id,
        "arm": arm,
        "t_s": t_s,
        "frame": int(t_s * 24),
        "model_id": "test-model",
        **extra,
    }


class AiInputUnitTests(unittest.TestCase):
    def write_inputs(
        self,
        directory: Path,
        counts: list[dict[str, object]],
        events: list[dict[str, object]],
    ) -> tuple[Path, Path]:
        counts_path = directory / "counts.jsonl"
        events_path = directory / "events.jsonl"
        counts_path.write_text("".join(json.dumps(item) + "\n" for item in counts), encoding="utf-8")
        events_path.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")
        return counts_path, events_path

    def test_initial_counts_mapping_and_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            counts, events = self.write_inputs(
                Path(temporary),
                [count_record(0.0, extra=True), count_record(1.0, extra=True)],
                [event_record(44, 0.542, future_emergency={"vehicle_type": "ambulance"})],
            )
            timeline = build_timeline(counts, events, MAPPING, SCENARIO_MAPPING)
        first = timeline.at_second(0)
        self.assertEqual(first.approaches["north"].observed_vehicles, 5)
        self.assertEqual(first.approaches["east"].new_arrival_track_ids, (44,))
        self.assertEqual(first.approaches["east"].sumo_incoming_edge_id, "east_in")
        self.assertEqual(first.in_intersection, 5)

    def test_strict_producer_and_tolerant_consumer_models_are_separate(self) -> None:
        event = event_record(
            44, 0.542, future_emergency={"vehicle_type": "ambulance"}
        )
        counts = count_record(0.0, extra=True)

        with self.assertRaises(ValidationError):
            GateEvent.model_validate(event)
        with self.assertRaises(ValidationError):
            GateCounts.model_validate(counts)

        consumed_event = GateEventInput.model_validate(event)
        consumed_counts = GateCountsInput.model_validate(counts)
        self.assertEqual(
            consumed_event.model_extra,
            {"future_emergency": {"vehicle_type": "ambulance"}},
        )
        self.assertEqual(
            consumed_counts.approaches["north"].model_extra,
            {"future_confidence": 0.9},
        )

    def test_tolerant_models_still_reject_malformed_known_fields(self) -> None:
        malformed_event = event_record(44, 0.542)
        malformed_event["track_id"] = "44"
        malformed_counts = count_record(0.0)
        malformed_counts["approaches"]["north"]["vehicles_on_approach"] = -1  # type: ignore[index]
        with self.assertRaises(ValidationError):
            GateEventInput.model_validate(malformed_event)
        with self.assertRaises(ValidationError):
            GateCountsInput.model_validate(malformed_counts)

    def test_tolerant_event_preserves_origin_arm_semantics(self) -> None:
        missing_origin = event_record(44, 0.542)
        missing_origin["event"] = "intersection_exited"
        with self.assertRaises(ValidationError):
            GateEventInput.model_validate(missing_origin)
        unexpected_origin = event_record(44, 0.542, origin_arm=None)
        with self.assertRaises(ValidationError):
            GateEventInput.model_validate(unexpected_origin)

    def warm_up_counts(self, known_from: int | None, seconds: int = 5) -> list[dict[str, object]]:
        """Causal-engine counts: lines before the warm-up carry no arms and in_intersection null."""
        lines = []
        for t in range(seconds):
            line = count_record(float(t))
            if known_from is None or t < known_from:
                line["approaches"], line["in_intersection"] = {}, None
            lines.append(line)
        return lines

    def test_initial_values_come_from_the_warm_up_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            counts, events = self.write_inputs(Path(temporary), self.warm_up_counts(3), [event_record(9, 3.5)])
            timeline = build_timeline(counts, events, MAPPING, SCENARIO_MAPPING)
        self.assertIsNone(timeline.points[0].approaches["north"].observed_vehicles)  # t_s 0 stays unknown
        self.assertEqual(timeline.initial_point.t_s, 3.0)
        summary = timeline.summary()
        self.assertEqual(summary["initial_observation_t_s"], 3.0)
        self.assertEqual(summary["initial_observed_vehicles"], {"north": 5, "east": 3, "south": 4, "west": 14})
        self.assertEqual(summary["initial_in_intersection"], 5)

    def test_initial_values_null_when_no_line_is_known(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            counts, events = self.write_inputs(Path(temporary), self.warm_up_counts(None), [event_record(9, 1.5)])
            timeline = build_timeline(counts, events, MAPPING, SCENARIO_MAPPING)
        summary = timeline.summary()
        self.assertIsNone(timeline.initial_point)
        self.assertIsNone(summary["initial_observation_t_s"])
        self.assertEqual(summary["initial_observed_vehicles"], {"north": None, "east": None, "south": None, "west": None})
        self.assertIsNone(summary["initial_in_intersection"])

    def test_older_files_keep_t_s_0_as_the_initial_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            counts, events = self.write_inputs(Path(temporary), self.warm_up_counts(0), [event_record(9, 1.5)])
            summary = build_timeline(counts, events, MAPPING, SCENARIO_MAPPING).summary()
        self.assertEqual(summary["initial_observation_t_s"], 0.0)
        self.assertEqual(summary["initial_observed_vehicles"]["west"], 14)

    def test_missing_arm_remains_unknown_but_arrival_is_retained(self) -> None:
        first = count_record(0.0)
        del first["approaches"]["north"]  # type: ignore[index]
        with tempfile.TemporaryDirectory() as temporary:
            counts, events = self.write_inputs(
                Path(temporary), [first], [event_record(9, 0.5, "north")]
            )
            timeline = build_timeline(counts, events, MAPPING, SCENARIO_MAPPING)
        north = timeline.points[0].approaches["north"]
        self.assertIsNone(north.observed_vehicles)
        self.assertIsNone(north.entered_total)
        self.assertEqual(north.new_arrival_track_ids, (9,))

    def test_missing_invalid_and_duplicate_arrival_inputs(self) -> None:
        with self.assertRaises(FileNotFoundError):
            build_timeline(Path("/missing/counts.jsonl"), Path("/missing/events.jsonl"))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            counts, events = self.write_inputs(
                directory,
                [count_record(0.0)],
                [event_record(1, 0.1), event_record(1, 0.2)],
            )
            with self.assertRaisesRegex(JsonlValidationError, "duplicate approach_entered"):
                build_timeline(counts, events, MAPPING, SCENARIO_MAPPING)
            events.write_text("not-json\n", encoding="utf-8")
            with self.assertRaisesRegex(JsonlValidationError, "events.jsonl:1"):
                build_timeline(counts, events, MAPPING, SCENARIO_MAPPING)


@unittest.skipUnless(
    (LOCAL_SAMPLE / "counts.jsonl").is_file() and (LOCAL_SAMPLE / "events.jsonl").is_file(),
    "local teammate AI sample is unavailable",
)
class RealAiSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.timeline = build_timeline(
            LOCAL_SAMPLE / "counts.jsonl",
            LOCAL_SAMPLE / "events.jsonl",
            MAPPING,
            SCENARIO_MAPPING,
        )

    def test_real_first_30_seconds(self) -> None:
        sample = [point for point in self.timeline.points if point.t_s < 30]
        self.assertEqual(len(sample), 30)
        track_ids = [
            track_id
            for point in sample
            for state in point.approaches.values()
            for track_id in state.new_arrival_track_ids
        ]
        self.assertEqual(len(track_ids), len(set(track_ids)))
        self.assertEqual(
            {
                arm: sum(point.approaches[arm].new_arrival_count for point in sample)
                for arm in sample[0].approaches
            },
            {"north": 0, "east": 1, "south": 2, "west": 29},
        )
        self.assertEqual(
            {arm: sample[0].approaches[arm].observed_vehicles for arm in sample[0].approaches},
            {"north": 5, "east": 3, "south": 4, "west": 14},
        )

    def test_full_264_second_integrity(self) -> None:
        summary = self.timeline.summary()
        self.assertEqual(summary["observation_count"], 264)
        self.assertEqual(summary["recording_end_s"], 264.0)
        self.assertEqual(
            summary["new_arrivals"],
            {"north": 37, "east": 45, "south": 134, "west": 109},
        )
        self.assertEqual(
            summary["final_cumulative"],
            {
                "north": {"entered_total": 37, "discharged_total": 40, "observed_vehicles": 2},
                "east": {"entered_total": 45, "discharged_total": 43, "observed_vehicles": 5},
                "south": {"entered_total": 134, "discharged_total": 134, "observed_vehicles": 4},
                "west": {"entered_total": 109, "discharged_total": 112, "observed_vehicles": 11},
            },
        )
        all_arrivals = [
            track_id
            for point in self.timeline.points
            for state in point.approaches.values()
            for track_id in state.new_arrival_track_ids
        ]
        self.assertEqual(len(all_arrivals), 325)
        self.assertEqual(len(all_arrivals), len(set(all_arrivals)))


if __name__ == "__main__":
    unittest.main()
