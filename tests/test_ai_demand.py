"""Tests for deterministic AI-arrival to SUMO route generation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from backend.simulation.ai_demand import derive_straight_routes, generate_demand
from backend.simulation.ai_input import (
    DEFAULT_MAPPING_PATH,
    DEFAULT_SCENARIO_MAPPING_PATH,
    JsonlValidationError,
    load_arm_mapping,
)


ROOT = Path(__file__).resolve().parents[1]
NETWORK = ROOT / "scenarios" / "single_intersection" / "demo.net.xml"
LOCAL_SAMPLE = Path.home() / "flowgency_ai_samples"


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")


def counts_record(t_s: float) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "t_s": t_s,
        "approaches": {
            "north": {"vehicles_on_approach": 5, "entered_total": 0, "discharged_total": 0},
            "east": {"vehicles_on_approach": 3, "entered_total": 0, "discharged_total": 0},
            "south": {"vehicles_on_approach": 4, "entered_total": 0, "discharged_total": 0},
            "west": {"vehicles_on_approach": 14, "entered_total": 0, "discharged_total": 0},
        },
        "in_intersection": 5,
        "model_id": "test-model",
    }


def arrival(track_id: int, arm: str, t_s: float, **extra: object) -> dict[str, object]:
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


class AiDemandUnitTests(unittest.TestCase):
    def test_initial_vehicles_come_from_the_warm_up_line(self) -> None:
        unknown = [{**counts_record(float(t)), "approaches": {}, "in_intersection": None} for t in range(3)]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            counts, events = directory / "counts.jsonl", directory / "events.jsonl"
            write_jsonl(counts, unknown + [counts_record(3.0), counts_record(4.0)])
            write_jsonl(events, [arrival(10, "north", 3.5)])
            summary = generate_demand(counts, events, directory / "generated.rou.xml")
            initial = summary["initial_observed_vehicles_not_inserted"]
            self.assertEqual(initial["observed_at_t_s"], 3.0)
            self.assertEqual(initial["by_camera_arm"], {"north": 5, "east": 3, "south": 4, "west": 14})
            self.assertEqual(initial["total"], 26)
            self.assertEqual(summary["vehicle_count"], 1)
            write_jsonl(counts, unknown)  # warm-up never completed: no starting offset is known
            write_jsonl(events, [arrival(10, "north", 1.5)])
            with self.assertRaisesRegex(JsonlValidationError, "vehicle count known for every arm"):
                generate_demand(counts, events, directory / "none.rou.xml")

    def test_simultaneous_arrivals_are_ordered_and_future_fields_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            counts = directory / "counts.jsonl"
            events = directory / "events.jsonl"
            output = directory / "generated.rou.xml"
            write_jsonl(counts, [counts_record(0.0), counts_record(1.0)])
            write_jsonl(events, [
                arrival(20, "east", 0.5, emergency={"vehicle_type": "ambulance"}),
                arrival(10, "north", 0.5, future_confidence=0.99),
            ])
            summary = generate_demand(counts, events, output)
            root = ET.parse(output).getroot()
        vehicles = root.findall("vehicle")
        self.assertEqual([item.get("id") for item in vehicles], ["ai_north_10", "ai_east_20"])
        self.assertEqual([item.get("depart") for item in vehicles], ["0.5", "0.5"])
        self.assertEqual({item.get("type") for item in vehicles}, {"ai_passenger_deterministic"})
        self.assertEqual(summary["vehicle_count"], 2)
        self.assertEqual(summary["initial_observed_vehicles_not_inserted"]["total"], 26)

    def test_invalid_straight_topology_fails(self) -> None:
        mapping = load_arm_mapping()
        with tempfile.TemporaryDirectory() as temporary:
            network = Path(temporary) / "invalid.net.xml"
            network.write_text(
                '<net><edge id="north_in"/><edge id="south_out"/>'
                '<connection from="north_in" to="south_out" dir="l"/></net>',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(JsonlValidationError, "straight routes"):
                derive_straight_routes(network, mapping)


@unittest.skipUnless(
    (LOCAL_SAMPLE / "counts.jsonl").is_file() and (LOCAL_SAMPLE / "events.jsonl").is_file(),
    "local teammate AI sample is unavailable",
)
class RealAiDemandTests(unittest.TestCase):
    def generate(self, directory: Path, name: str) -> tuple[Path, Path, dict[str, object]]:
        output = directory / f"{name}.rou.xml"
        summary_path = directory / f"{name}.summary.json"
        summary = generate_demand(
            LOCAL_SAMPLE / "counts.jsonl",
            LOCAL_SAMPLE / "events.jsonl",
            output,
            summary_path=summary_path,
        )
        return output, summary_path, summary

    def test_full_sample_exact_arrivals_timestamps_and_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, _, summary = self.generate(Path(temporary), "ai")
            root = ET.parse(output).getroot()
        vehicles = root.findall("vehicle")
        self.assertEqual(len(vehicles), 325)
        self.assertEqual(len({item.get("id") for item in vehicles}), 325)
        self.assertEqual(
            summary["arrivals_by_camera_arm"],
            {"north": 37, "east": 45, "south": 134, "west": 109},
        )
        self.assertEqual(summary["arrival_time_range_s"], {"first": 0.542, "last": 261.637})
        self.assertEqual(summary["initial_observed_vehicles_not_inserted"]["total"], 26)
        self.assertEqual(len(root.findall("route")), 4)

        source_arrivals = [
            json.loads(line)
            for line in (LOCAL_SAMPLE / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if json.loads(line)["event"] == "approach_entered"
        ]
        expected = {
            f"ai_{event['arm']}_{event['track_id']}": (event["arm"], float(event["t_s"]))
            for event in source_arrivals
        }
        actual = {
            vehicle.get("id"): (
                vehicle.get("route", "").removeprefix("ai_straight_"),
                float(vehicle.get("depart", "nan")),
            )
            for vehicle in vehicles
        }
        self.assertEqual(actual, expected)

    def test_output_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first_route, first_summary, _ = self.generate(directory, "first")
            second_route, second_summary, _ = self.generate(directory, "second")
            self.assertEqual(first_route.read_bytes(), second_route.read_bytes())
            self.assertEqual(first_summary.read_bytes(), second_summary.read_bytes())

    def test_generated_routes_match_verified_straight_connections(self) -> None:
        routes = derive_straight_routes(NETWORK, load_arm_mapping())
        self.assertEqual(
            {arm: (route.incoming_edge_id, route.outgoing_edge_id) for arm, route in routes.items()},
            {
                "north": ("north_in", "south_out"),
                "east": ("east_in", "west_out"),
                "south": ("south_in", "north_out"),
                "west": ("west_in", "east_out"),
            },
        )


if __name__ == "__main__":
    unittest.main()
