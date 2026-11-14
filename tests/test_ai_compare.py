from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.simulation.ai_compare import (
    ComparisonError,
    compare_experiments,
    compare_metric,
)


class AiComparisonTests(unittest.TestCase):
    def _write_run(
        self,
        root: Path,
        mode: str,
        *,
        depart: float = 2.0,
        arrival: float = 10.0,
        waiting: float = 3.0,
        time_loss: float = 4.0,
        planned: float = 1.0,
        teleports: int = 0,
        adaptive_strategy: str | None = None,
    ) -> Path:
        directory = root / mode
        directory.mkdir()
        network = root / "network.net.xml"
        network.write_text("<net/>", encoding="utf-8")
        route = directory / "ai_demand.rou.xml"
        route.write_text(
            "<routes>"
            '<route id="straight" edges="in out"/>'
            f'<vehicle id="ai_north_1" type="car" route="straight" depart="{planned}" '
            'departLane="best" departSpeed="max" departPos="base"/>'
            "</routes>",
            encoding="utf-8",
        )
        prefix = "fixed" if mode == "fixed" else "adaptive"
        (directory / f"{prefix}_runtime.sumocfg").write_text(
            "<configuration>"
            f'<input><net-file value="{network}"/><route-files value="{route}"/></input>'
            '<time><begin value="0"/><end value="1800"/><step-length value="1"/></time>'
            '<random_number><seed value="42"/></random_number>'
            '<output><tripinfo-output.write-unfinished value="true"/>'
            '<summary-output.period value="1"/></output>'
            '<processing><collision.action value="warn"/>'
            '<collision.check-junctions value="true"/>'
            '<time-to-teleport value="300"/></processing>'
            "</configuration>",
            encoding="utf-8",
        )
        (directory / "tripinfo.xml").write_text(
            "<tripinfos>"
            f'<tripinfo id="ai_north_1" depart="{depart}" arrival="{arrival}" '
            f'waitingTime="{waiting}" timeLoss="{time_loss}"/>'
            "</tripinfos>",
            encoding="utf-8",
        )
        (directory / "summary.xml").write_text(
            f'<summary><step time="{arrival}" collisions="0" teleports="{teleports}"/></summary>',
            encoding="utf-8",
        )
        (directory / "collisions.xml").write_text(
            "<collisions/>", encoding="utf-8"
        )
        sources = {"counts_sha256": "counts", "events_sha256": "events"}
        (directory / "ai_demand.summary.json").write_text(
            json.dumps({"sources": sources}), encoding="utf-8"
        )
        run_report = {
                "control_mode": mode,
                "validation": {"passed": True},
                "diagnostics": {"collisions": 0, "teleports": teleports},
                "vehicles": {
                    "planned": 1,
                    "inserted": 1,
                    "arrived": 1,
                    "unfinished": 0,
                },
            }
        if mode == "adaptive" and adaptive_strategy is not None:
            run_report["controller_provenance"] = {
                "selected_strategy": adaptive_strategy,
                "profile_id": (
                    "single_intersection_gap_v1_experimental"
                    if adaptive_strategy == "gap_v1"
                    else "legacy_synthetic_adaptive"
                ),
                "manifest_path": (
                    "/sanitized/gap.json" if adaptive_strategy == "gap_v1" else None
                ),
                "manifest_sha256": (
                    "manifest-hash" if adaptive_strategy == "gap_v1" else None
                ),
                "active_traffic_light_ids": ["demo_01"],
                "active_strategies": [adaptive_strategy],
                "active_strategy_verified_at_runtime": True,
                "gap_release_decision_count": 2 if adaptive_strategy == "gap_v1" else 0,
                "validation_errors": [],
            }
        (directory / f"{prefix}_run_summary.json").write_text(
            json.dumps(run_report),
            encoding="utf-8",
        )
        return directory

    def test_valid_pair_computes_per_vehicle_and_regression_signs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixed = self._write_run(root, "fixed")
            adaptive = self._write_run(
                root,
                "adaptive",
                depart=3,
                arrival=12,
                waiting=5,
                time_loss=6,
            )
            report, rows = compare_experiments(fixed, adaptive)
        self.assertTrue(report["validation"]["passed"])
        waiting = report["comparison"]["total_waiting_time_s"]
        self.assertEqual(waiting["adaptive_minus_fixed"], 2)
        self.assertEqual(waiting["improvement_percent"], -66.667)
        self.assertEqual(waiting["outcome"], "regression")
        self.assertEqual(
            report["comparison"]["average_waiting_time_s"]["adaptive"], 5
        )
        self.assertEqual(
            report["comparison"]["average_time_loss_s"]["adaptive"], 6
        )
        self.assertEqual(rows[0]["fixed_planned_to_arrival_s"], 9)
        self.assertEqual(rows[0]["adaptive_planned_to_arrival_s"], 11)

    def test_metric_signs_distinguish_savings_and_regression(self) -> None:
        improved = compare_metric(100, 80)
        regressed = compare_metric(100, 120)
        self.assertEqual(improved["improvement_percent"], 20)
        self.assertEqual(improved["outcome"], "improvement")
        self.assertEqual(regressed["improvement_percent"], -20)
        self.assertEqual(regressed["percent_change"], 20)

    def test_mismatched_demand_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixed = self._write_run(root, "fixed")
            adaptive = self._write_run(root, "adaptive", planned=2)
            with self.assertRaisesRegex(ComparisonError, "route files differ"):
                compare_experiments(fixed, adaptive)

    def test_unfinished_or_teleported_run_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixed = self._write_run(root, "fixed")
            unfinished = self._write_run(root, "adaptive", arrival=-1)
            with self.assertRaisesRegex(ComparisonError, "unfinished"):
                compare_experiments(fixed, unfinished)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixed = self._write_run(root, "fixed")
            teleported = self._write_run(root, "adaptive", teleports=1)
            with self.assertRaisesRegex(ComparisonError, "collisions or teleports"):
                compare_experiments(fixed, teleported)

    def test_gap_v1_comparison_requires_matching_runtime_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixed = self._write_run(root, "fixed")
            adaptive = self._write_run(
                root, "adaptive", adaptive_strategy="gap_v1"
            )
            report, _rows = compare_experiments(
                fixed, adaptive, adaptive_strategy="gap_v1"
            )
            self.assertEqual(
                report["adaptive_controller"]["selected_strategy"], "gap_v1"
            )
            self.assertEqual(
                report["adaptive_controller"]["gap_release_decision_count"], 2
            )
            with self.assertRaisesRegex(ComparisonError, "not requested"):
                compare_experiments(fixed, adaptive)

    def test_historical_legacy_report_remains_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixed = self._write_run(root, "fixed")
            adaptive = self._write_run(root, "adaptive")
            report, _rows = compare_experiments(fixed, adaptive)
        self.assertTrue(
            report["adaptive_controller"][
                "historical_report_without_runtime_provenance"
            ]
        )


if __name__ == "__main__":
    unittest.main()
