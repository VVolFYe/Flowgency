"""Static registry for selectable, repository-owned SUMO scenarios."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_ROOT = REPOSITORY_ROOT / "scenarios"
DEFAULT_SCENARIO_ID = "single_intersection"


class ScenarioNotFound(ValueError):
    """Raised when an API scenario selection ID is unknown."""


@dataclass(frozen=True)
class ScenarioDefinition:
    scenario_id: str
    display_name: str
    description: str
    config_path: Path
    network_path: Path
    mapping_path: Path | None
    output_directory: Path
    legacy_scenario_id: str
    coordinate_system: str
    seed: int
    supports_adaptive_control: bool = False
    default_control_mode: str = "fixed"
    known_limitation: str | None = None


_SINGLE = SCENARIOS_ROOT / "single_intersection"
_LONDON = SCENARIOS_ROOT / "london_network"

SCENARIOS: dict[str, ScenarioDefinition] = {
    DEFAULT_SCENARIO_ID: ScenarioDefinition(
        scenario_id=DEFAULT_SCENARIO_ID,
        display_name="Single intersection",
        description="Synthetic four-approach signalized intersection.",
        config_path=_SINGLE / "demo.sumocfg",
        network_path=_SINGLE / "demo.net.xml",
        mapping_path=_SINGLE / "mappings.json",
        output_directory=_SINGLE / "output",
        legacy_scenario_id="single-intersection-v1",
        coordinate_system="synthetic_cartesian_metres",
        seed=42,
        supports_adaptive_control=True,
    ),
    "single_intersection_emergency": ScenarioDefinition(
        scenario_id="single_intersection_emergency",
        display_name="Emergency priority demo",
        description="Synthetic junction with marked ambulance, fire brigade, and police vehicles.",
        config_path=_SINGLE / "emergency.sumocfg",
        network_path=_SINGLE / "demo.net.xml",
        mapping_path=_SINGLE / "mappings.json",
        output_directory=_SINGLE / "output" / "emergency",
        legacy_scenario_id="single-intersection-v1",
        coordinate_system="synthetic_cartesian_metres",
        seed=42,
        supports_adaptive_control=True,
        default_control_mode="adaptive_with_emergency_priority",
        known_limitation="Simulation demonstration; no pedestrian crossings are modeled.",
    ),
    "london_normal": ScenarioDefinition(
        scenario_id="london_normal",
        display_name="London — Normal",
        description="Moderate deterministic traffic in the Oval/Kennington network.",
        config_path=_LONDON / "configs" / "normal.sumocfg",
        network_path=_LONDON / "london.net.xml",
        mapping_path=None,
        output_directory=_LONDON / "output" / "normal",
        legacy_scenario_id="london-oval-kennington-v1",
        coordinate_system="sumo_cartesian_metres_utm_zone_30",
        seed=20261113,
    ),
    "london_rush_hour": ScenarioDefinition(
        scenario_id="london_rush_hour",
        display_name="London — Rush hour",
        description="Higher deterministic demand with meaningful queues.",
        config_path=_LONDON / "configs" / "rush_hour.sumocfg",
        network_path=_LONDON / "london.net.xml",
        mapping_path=None,
        output_directory=_LONDON / "output" / "rush_hour",
        legacy_scenario_id="london-oval-kennington-v1",
        coordinate_system="sumo_cartesian_metres_utm_zone_30",
        seed=20261113,
        known_limitation="Four deterministic J5 teleports are documented and expected.",
    ),
    "london_unbalanced": ScenarioDefinition(
        scenario_id="london_unbalanced",
        display_name="London — Unbalanced",
        description="Asymmetric deterministic demand focused on the J3 corridor.",
        config_path=_LONDON / "configs" / "unbalanced.sumocfg",
        network_path=_LONDON / "london.net.xml",
        mapping_path=None,
        output_directory=_LONDON / "output" / "unbalanced",
        legacy_scenario_id="london-oval-kennington-v1",
        coordinate_system="sumo_cartesian_metres_utm_zone_30",
        seed=20261113,
    ),
}


def get_scenario(scenario_id: str = DEFAULT_SCENARIO_ID) -> ScenarioDefinition:
    try:
        return SCENARIOS[scenario_id]
    except KeyError as exc:
        choices = ", ".join(SCENARIOS)
        raise ScenarioNotFound(
            f"unknown scenario_id '{scenario_id}'; expected one of: {choices}"
        ) from exc


@lru_cache(maxsize=1)
def _london_targets() -> list[dict[str, Any]]:
    source = _LONDON / "mapping_candidates.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    return [
        {
            "intersection_id": target["intersection_id"],
            "target_location": target["target_location"],
            "jamcam_id": target["jamcam_id"],
            "mapping_status": target["mapping_status"],
            "latitude": target["latitude"],
            "longitude": target["longitude"],
            "candidates": [
                {
                    "junction_id": candidate["junction_id"],
                    "traffic_light_id": candidate["traffic_light_id"],
                    "incoming_edges": candidate["incoming_edges"],
                }
                for candidate in target["candidates"]
            ],
        }
        for target in data["targets"]
    ]


def list_scenarios() -> list[dict[str, Any]]:
    """Return public metadata without parsing a SUMO network or starting TraCI."""
    result = []
    for scenario in SCENARIOS.values():
        item: dict[str, Any] = {
            "scenario_id": scenario.scenario_id,
            "display_name": scenario.display_name,
            "description": scenario.description,
            "coordinate_system": scenario.coordinate_system,
            "supports_adaptive_control": scenario.supports_adaptive_control,
            "default_control_mode": scenario.default_control_mode,
            "known_limitation": scenario.known_limitation,
            "target_mappings": (
                copy.deepcopy(_london_targets())
                if scenario.legacy_scenario_id == "london-oval-kennington-v1"
                else []
            ),
        }
        result.append(item)
    return result
