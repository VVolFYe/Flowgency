"""Static analytics export from compare_cycles, on a small fixture (no SUMO)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.simulation import analytics, compare_cycles
from backend.simulation.compare_cycles import build_analytics_report, read_tripinfo

ROUTES = """<routes>
  <vehicle id="a" depart="0"/><vehicle id="b" depart="10"/>
  <vehicle id="c" depart="20"/><vehicle id="amb" depart="30" type="ambulance"/>
</routes>"""
CONFIG = """<configuration>
  <input><net-file value="net.net.xml"/><route-files value="demand.rou.xml"/></input>
  <time><begin value="0"/><end value="400"/></time>
  <random_number><seed value="7"/></random_number>
</configuration>"""
MANIFEST = '{"profile_id": "fixture_v1", "controllers": [{"traffic_light_id": "J1"}]}'


def tripinfo_xml(rows: list[tuple[str, str, float, float, float, float]]) -> str:
    body = "".join(
        f'<tripinfo id="{vid}" vType="{vtype}" depart="{depart}" arrival="{depart + duration}" '
        f'waitingTime="{waiting}" timeLoss="{loss}" duration="{duration}"/>'
        for vid, vtype, depart, waiting, loss, duration in rows
    )
    return f"<tripinfos>{body}</tripinfos>"


FIXED_TRIPS = [
    ("a", "passenger", 0, 10, 20, 100), ("b", "passenger", 10, 20, 30, 110),
    ("c", "passenger", 20, 30, 40, 120), ("amb", "ambulance", 30, 0, 10, 90),
]
ADAPTIVE_TRIPS = [
    ("a", "passenger", 0, 5, 15, 95), ("b", "passenger", 10, 10, 20, 100),
    ("c", "passenger", 20, 15, 25, 105), ("amb", "ambulance", 30, 0, 8, 88),
]


def samples(queues: list[int], tls_queues: list[list[int]], greens: dict[str, list[float]]):
    return {
        "schema_version": "1.0",
        "queue_measurement": analytics.QUEUE_MEASUREMENT,
        "traffic_light_ids": ["J1", "J2"],
        "steps": [
            {"t_s": float(t + 1), "network_queue_vehicles": q, "active_vehicles": q + 1,
             "arrived_cumulative": t // 10, "tls_queue_vehicles": tls_queues[t]}
            for t, q in enumerate(queues)
        ],
        "green_phase_durations_s": greens,
    }


def run_result(mode: str, teleports: int = 0) -> dict:
    return {
        "exit_code": 0 if not teleports else 1, "terminated_by_step_limit": False,
        "departed": 4, "arrived": 4, "departed_vehicle_ids": ["a", "b", "c", "amb"],
        "arrived_vehicle_ids": ["a", "b", "c", "amb"], "collisions": 0, "teleports": teleports,
        "steps": 25, "cycle_decisions": 2 if mode == "adaptive" else 0,
        "cycle_decision_events": (
            [{"traffic_light_id": "J1"}, {"traffic_light_id": "J1"}] if mode == "adaptive" else []
        ),
        "adaptive_profile_id": "fixture_v1" if mode == "adaptive" else None,
        "adaptive_controller_ids": ["J1"] if mode == "adaptive" else [],
        "fixed_controllers": {"J2": "no competing green"} if mode == "adaptive" else {},
    }


class Fixture:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        (directory / "demand.rou.xml").write_text(ROUTES, encoding="utf-8")
        self.config = directory / "scenario.sumocfg"
        self.config.write_text(CONFIG, encoding="utf-8")
        self.manifest = directory / "manifest.json"
        self.manifest.write_text(MANIFEST, encoding="utf-8")
        self.expected = compare_cycles.read_expected_vehicle_ids(self.config)
        self.metadata = compare_cycles.manifest_metadata(self.manifest)

    def tripinfo(self, mode: str, rows) -> dict:
        path = self.directory / f"{mode}_tripinfo.xml"
        path.write_text(tripinfo_xml(rows), encoding="utf-8")
        return read_tripinfo(path)

    def build(self, *, runs, tripinfos, validation, sample_map):
        return build_analytics_report(
            scenario_id="fixture", scenario_name="Fixture", config=self.config,
            manifest=self.manifest, expected_ids=self.expected,
            adaptive_metadata=self.metadata, runs=runs, tripinfos=tripinfos,
            validation=validation, samples=sample_map,
            report_path=self.directory / "report.json", created_on="2026-11-14",
        )


class StatisticsTests(unittest.TestCase):
    def test_percentile_matches_linear_interpolation(self) -> None:
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        self.assertAlmostEqual(analytics.percentile(values, 0.5), 5.5)
        self.assertAlmostEqual(analytics.percentile(values, 0.9), 9.1)
        self.assertAlmostEqual(analytics.percentile(values, 0.95), 9.55)
        self.assertEqual(analytics.percentile([4.0], 0.95), 4.0)
        self.assertIsNone(analytics.percentile([], 0.5))

    def test_bin_edges_are_shared_and_cover_both_modes(self) -> None:
        edges = analytics.shared_bin_edges([[0, 3, 9], [41]])
        self.assertEqual(edges[0], 0)
        self.assertLess(41, edges[-1])
        widths = {round(b - a, 6) for a, b in zip(edges, edges[1:])}
        self.assertEqual(widths, {2.5})
        self.assertEqual(analytics.histogram([0, 2.5, 41], edges)[0:2], [1, 1])
        self.assertEqual(sum(analytics.histogram([0, 2.5, 41], edges)), 3)
        self.assertEqual(analytics.shared_bin_edges([[0, 0]]), [0.0, 1.0])
        self.assertIsNone(analytics.shared_bin_edges([None, []]))

    def test_downsample_keeps_interval_boundaries_and_final_step(self) -> None:
        steps = [{"t_s": float(t), "network_queue_vehicles": t, "active_vehicles": 0,
                  "arrived_cumulative": t} for t in range(1, 26)]
        rows = analytics.downsample(steps, 10.0)
        self.assertEqual([row["t_s"] for row in rows], [10.0, 20.0, 25.0])
        self.assertEqual(analytics.timeseries_interval([12000.0]), 20.0)

    def test_throughput_and_unknowns(self) -> None:
        records = [{"arrival_s": 1800.0}, {"arrival_s": 3600.0}]
        self.assertEqual(analytics.throughput_vehicles_per_hour(records, 0.0), 2.0)
        self.assertIsNone(analytics.throughput_vehicles_per_hour([], 0.0))
        self.assertIsNone(analytics.throughput_vehicles_per_hour(None, 0.0))
        self.assertIsNone(analytics.emergency_stats([{"vehicle_type": None, "time_loss_s": 1}],
                                                    frozenset({"ambulance"})))
        unknown = analytics.paired(None, 4.0)
        self.assertEqual(unknown["adaptive"], 4.0)
        self.assertIsNone(unknown["absolute_improvement"])
        self.assertEqual(analytics.paired(100.0, 110.0, better="higher")["percentage_improvement"], 10.0)

    def test_green_state_classification(self) -> None:
        self.assertTrue(analytics.is_green_state("GGrr"))
        self.assertTrue(analytics.is_green_state("grrr"))
        self.assertFalse(analytics.is_green_state("GGyy"))
        self.assertFalse(analytics.is_green_state("rrrr"))


class FakeTraci:
    """Two controllers, three lanes (one shared), scripted phases and halts."""

    def __init__(self) -> None:
        self.time = 0.0
        self.phase = {"J1": 0, "J2": 0}
        self.halting = {"l1": 0, "l2": 0, "shared": 0}
        outer = self

        class Light:
            def getIDList(self): return ["J2", "J1"]
            def getControlledLanes(self, tls): return {"J1": ["l1", "shared", "l1"], "J2": ["l2", "shared"]}[tls]
            def getPhase(self, tls): return outer.phase[tls]
            def getRedYellowGreenState(self, tls): return ["GGr", "yyr", "rrr"][outer.phase[tls]]

        class Lane:
            def getLastStepHaltingNumber(self, lane): return outer.halting[lane]

        class Simulation:
            def getTime(self): return outer.time

        class Vehicle:
            def getIDCount(self): return 5

        self.trafficlight, self.lane, self.simulation, self.vehicle = Light(), Lane(), Simulation(), Vehicle()


class StepSamplerTests(unittest.TestCase):
    def test_unique_lanes_and_completed_green_phases(self) -> None:
        traci = FakeTraci()
        sampler = analytics.StepSampler(traci)
        script = [(1, {"l1": 1, "l2": 0, "shared": 2}, 0), (2, {"l1": 0, "l2": 3, "shared": 2}, 1),
                  (3, {"l1": 0, "l2": 0, "shared": 0}, 2)]
        for t, halting, j1_phase in script:
            traci.time, traci.halting, traci.phase["J1"] = float(t), halting, j1_phase
            sampler.record(arrived_cumulative=t)
        data = sampler.to_json()
        self.assertEqual(data["traffic_light_ids"], ["J1", "J2"])
        self.assertEqual([s["network_queue_vehicles"] for s in data["steps"]], [3, 5, 0])
        self.assertEqual([s["tls_queue_vehicles"] for s in data["steps"]], [[3, 2], [2, 5], [0, 0]])
        # J1 green ran 0-2 s; the amber phase 2-3 s is not green; J2 never completed a phase.
        self.assertEqual(data["green_phase_durations_s"], {"J1": [2.0], "J2": []})


class AnalyticsReportTests(unittest.TestCase):
    def test_valid_fixture_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            tripinfos = {"fixed": fixture.tripinfo("fixed", FIXED_TRIPS),
                         "adaptive": fixture.tripinfo("adaptive", ADAPTIVE_TRIPS)}
            runs = {mode: run_result(mode) for mode in ("fixed", "adaptive")}
            validation = {mode: compare_cycles.validate_run(runs[mode], tripinfos[mode], fixture.expected)
                          for mode in runs}
            sample_map = {
                "fixed": samples([2] * 25, [[2, 0]] * 25, {"J1": [30.0, 30.0], "J2": []}),
                "adaptive": samples([1] * 24 + [5], [[1, 0]] * 24 + [[5, 0]], {"J1": [20.0, 40.0, 30.0], "J2": []}),
            }
            report = fixture.build(runs=runs, tripinfos=tripinfos, validation=validation,
                                   sample_map=sample_map)

        self.assertEqual(report["schema_version"], "1.0")
        self.assertTrue(report["validation"]["passed"])
        self.assertEqual(report["validation"]["matched_vehicle_count"], 4)
        self.assertEqual(report["validation"]["fixed"]["duplicate_tripinfo_ids"], 0)
        summary = report["summary"]
        # Totals/averages come straight from compare(): waiting 60 -> 30 s.
        self.assertEqual(summary["total_waiting_time_s"]["fixed"], 60.0)
        self.assertEqual(summary["total_waiting_time_s"]["absolute_improvement"], 30.0)
        self.assertEqual(summary["average_waiting_time_s"]["absolute_improvement"], 7.5)
        self.assertEqual(summary["average_waiting_time_s"]["percentage_improvement"], 50.0)
        # 4 trips, last arrival 140 s (fixed) vs 125 s (adaptive), begin 0 s.
        self.assertEqual(summary["throughput_vehicles_per_hour"]["fixed"], round(4 * 3600 / 140, 3))
        self.assertGreater(summary["throughput_vehicles_per_hour"]["absolute_improvement"], 0)
        self.assertEqual(summary["mean_network_queue_vehicles"]["fixed"], 2.0)
        self.assertEqual(summary["max_network_queue_vehicles"]["adaptive"], 5)
        self.assertEqual(summary["max_network_queue_vehicles"]["absolute_improvement"], -3)

        series = report["timeseries"]
        self.assertEqual([row["t_s"] for row in series["fixed"]], [10.0, 20.0, 25.0])
        self.assertEqual(set(series["fixed"][0]),
                         {"t_s", "network_queue_vehicles", "active_vehicles", "arrived_cumulative"})

        waiting = report["distributions"]["waiting_time_s"]
        self.assertEqual(waiting["fixed"]["max"], 30.0)
        self.assertEqual(waiting["fixed"]["p50"], 15.0)
        self.assertEqual(len(waiting["fixed"]["histogram"]), len(waiting["bin_edges"]) - 1)
        self.assertEqual(sum(waiting["adaptive"]["histogram"]), 4)

        j1 = report["intersections"]["adaptive"]["J1"]
        self.assertEqual(j1["decision_count"], 2)
        self.assertEqual(j1["mean_green_s"], 30.0)
        self.assertEqual(report["intersections"]["fixed"]["J1"]["decision_count"], 0)
        self.assertIsNone(report["intersections"]["fixed"]["J2"]["mean_green_s"])

        emergency = report["emergency"]
        self.assertEqual(emergency["fixed"]["emergency_average_time_loss_s"], 10.0)
        self.assertEqual(emergency["adaptive"]["normal_average_time_loss_s"], 20.0)
        self.assertEqual(report["experiment"]["adaptive_controller_count"], 1)
        self.assertIn("1 of 2", report["experiment"]["adaptive_scope"])
        self.assertEqual(report["provenance"]["seed"], 7)
        self.assertLess(len(json.dumps(report)), 200_000)

    def test_failed_validation_and_missing_samples_stay_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            no_ambulance = [row for row in FIXED_TRIPS if row[0] != "amb"]
            tripinfos = {"fixed": fixture.tripinfo("fixed", no_ambulance),
                         "adaptive": fixture.tripinfo("adaptive", ADAPTIVE_TRIPS[:2])}
            runs = {"fixed": run_result("fixed"), "adaptive": run_result("adaptive", teleports=4)}
            validation = {mode: compare_cycles.validate_run(runs[mode], tripinfos[mode], fixture.expected)
                          for mode in runs}
            report = fixture.build(runs=runs, tripinfos=tripinfos, validation=validation,
                                   sample_map={"fixed": None, "adaptive": None})

        self.assertFalse(report["validation"]["passed"])
        self.assertIn("run reported collisions or teleports", report["validation"]["adaptive"]["errors"])
        self.assertTrue(any(error.startswith("adaptive: ") for error in report["validation"]["errors"]))
        self.assertEqual(report["validation"]["adaptive"]["teleports"], 4)
        self.assertIsNone(report["validation"]["matched_vehicle_count"])
        self.assertIsNone(report["summary"]["total_waiting_time_s"]["fixed"])
        self.assertIsNone(report["summary"]["mean_network_queue_vehicles"]["fixed"])
        self.assertIsNotNone(report["summary"]["throughput_vehicles_per_hour"]["fixed"])
        self.assertIsNone(report["timeseries"]["fixed"])
        self.assertIsNone(report["intersections"]["adaptive"])
        self.assertIsNone(report["emergency"])
        self.assertTrue(any("teleport" in item for item in report["limitations"]))
        self.assertTrue(any("Validation failed" in item for item in report["limitations"]))


class CliWiringTests(unittest.TestCase):
    def test_analytics_out_writes_file_and_index_without_changing_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            output = fixture.directory / "out"
            public = fixture.directory / "public"
            trips = {"fixed": FIXED_TRIPS, "adaptive": ADAPTIVE_TRIPS}
            seen_samples: list[Path | None] = []

            def fake_run_mode(config, manifest, mode, out, binary, steps, analytics_samples=None):
                out.mkdir(parents=True, exist_ok=True)
                (out / "tripinfo.xml").write_text(tripinfo_xml(trips[mode]), encoding="utf-8")
                seen_samples.append(analytics_samples)
                if analytics_samples is not None:
                    analytics_samples.write_text(json.dumps(
                        samples([1] * 25, [[1, 0]] * 25, {"J1": [30.0], "J2": []})), encoding="utf-8")
                return run_result(mode)

            argv = ["compare_cycles", "--config", str(fixture.config),
                    "--adaptive-manifest", str(fixture.manifest),
                    "--output-directory", str(output), "--scenario-id", "fixture"]
            with mock.patch.object(compare_cycles, "run_mode", fake_run_mode), \
                    mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
                self.assertEqual(compare_cycles.main(), 0)
            baseline = json.loads((output / "comparison_report.json").read_text(encoding="utf-8"))
            self.assertEqual(seen_samples, [None, None])
            self.assertFalse((public / "fixture.json").exists())

            argv += ["--analytics-out", str(public / "fixture.json"),
                     "--analytics-index", str(public / "index.json"), "--scenario-name", "Fixture"]
            with mock.patch.object(compare_cycles, "run_mode", fake_run_mode), \
                    mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
                self.assertEqual(compare_cycles.main(), 0)
            report = json.loads((output / "comparison_report.json").read_text(encoding="utf-8"))
            exported = json.loads((public / "fixture.json").read_text(encoding="utf-8"))
            index = json.loads((public / "index.json").read_text(encoding="utf-8"))

        self.assertEqual(report, baseline)  # existing output unchanged by the new flag
        self.assertEqual(exported["scenario_name"], "Fixture")
        self.assertEqual(exported["summary"]["mean_network_queue_vehicles"]["fixed"], 1.0)
        self.assertEqual(index, [{"id": "fixture", "label": "Fixture", "kind": "simulation",
                                  "file": "fixture.json"}])


if __name__ == "__main__":
    unittest.main()
