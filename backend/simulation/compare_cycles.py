"""Compare fixed and configured adaptive timing on identical SUMO demand."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from .runner import REPOSITORY_ROOT


def read_trips(path: Path) -> dict[str, dict[str, float]]:
    trips: dict[str, dict[str, float]] = {}
    for item in ET.parse(path).getroot().iter("tripinfo"):
        if float(item.get("arrival", "-1")) < 0:
            continue
        trips[item.attrib["id"]] = {
            "waiting_s": float(item.attrib["waitingTime"]),
            "time_loss_s": float(item.attrib["timeLoss"]),
            "duration_s": float(item.attrib["duration"]),
        }
    return trips


def compare(fixed: dict[str, dict[str, float]], adaptive: dict[str, dict[str, float]]) -> dict:
    if not fixed or fixed.keys() != adaptive.keys():
        raise ValueError("completed vehicle IDs differ between runs; results are not comparable")
    count = len(fixed)
    result: dict = {"matched_vehicles": count}
    for field in ("waiting_s", "time_loss_s", "duration_s"):
        fixed_total = sum(trip[field] for trip in fixed.values())
        adaptive_total = sum(trip[field] for trip in adaptive.values())
        result[field] = {
            "fixed_average": round(fixed_total / count, 3),
            "adaptive_average": round(adaptive_total / count, 3),
            "average_saved": round((fixed_total - adaptive_total) / count, 3),
            "total_saved": round(fixed_total - adaptive_total, 3),
            "percent_saved": round(100 * (fixed_total - adaptive_total) / fixed_total, 2)
            if fixed_total else None,
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--adaptive-manifest", type=Path, required=True)
    parser.add_argument("--sumo-binary", default="sumo")
    args = parser.parse_args()
    config = args.config.resolve()
    manifest = args.adaptive_manifest.resolve()
    if not config.is_file() or not manifest.is_file():
        parser.error("config and adaptive manifest must exist")
    base = config.parent / "output" / f"comparison_{config.stem}"
    results = {}
    trips = {}
    for mode in ("fixed", "adaptive"):
        output = base / mode
        command = [sys.executable, "-m", "backend.simulation.cycle_run",
                   "--config", str(config), "--sumo-binary", args.sumo_binary,
                   "--output-directory", str(output)]
        if mode == "adaptive":
            command.extend(["--adaptive-manifest", str(manifest)])
        completed = subprocess.run(command, cwd=REPOSITORY_ROOT, text=True, capture_output=True, check=False)
        try:
            results[mode] = json.loads(completed.stdout.strip())
            trips[mode] = read_trips(output / "tripinfo.xml")
        except (ValueError, OSError, ET.ParseError) as exc:
            raise RuntimeError(f"{mode} run failed: {completed.stderr[-2000:]}") from exc
        results[mode]["exit_code"] = completed.returncode
    savings = compare(trips["fixed"], trips["adaptive"])
    print(json.dumps({"scenario_config": str(config), "fixed": results["fixed"],
                      "adaptive": results["adaptive"], "comparison": savings}, indent=2))
    return 0 if all(results[mode]["exit_code"] == 0 for mode in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
