"""Static registry for selectable, repository-owned SUMO scenarios."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_ROOT = REPOSITORY_ROOT / "scenarios"
DEFAULT_SCENARIO_ID = "single_intersection"
DEFAULT_NETWORK = "single_intersection"
DEFAULT_TRAFFIC_PROFILE = "normal"
DEFAULT_CONTROLLER_MODE = "fixed_timing"

NetworkId = Literal["single_intersection", "london"]
TrafficProfile = Literal["normal", "rush_hour", "unbalanced"]
ControllerMode = Literal[
    "fixed_timing", "adaptive_network", "adaptive_emergency_priority"
]

NETWORK_IDS = ("single_intersection", "london")
TRAFFIC_PROFILES = ("normal", "rush_hour", "unbalanced")
CONTROLLER_MODES = (
    "fixed_timing",
    "adaptive_network",
    "adaptive_emergency_priority",
)


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
    adaptive_manifest_path: Path | None = None
    supports_emergency_priority: bool = False
    default_control_mode: str = "fixed"
    known_limitation: str | None = None
    network: str = DEFAULT_NETWORK
    traffic_profile: str = DEFAULT_TRAFFIC_PROFILE
    emergency_vehicles_enabled: bool = False


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
        supports_emergency_priority=True,
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
        supports_emergency_priority=True,
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
        supports_adaptive_control=True,
        adaptive_manifest_path=_LONDON / "network_gap.json",
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
        supports_adaptive_control=True,
        adaptive_manifest_path=_LONDON / "network_gap.json",
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
        supports_adaptive_control=True,
        adaptive_manifest_path=_LONDON / "network_gap.json",
    ),
}


@dataclass(frozen=True)
class SimulationConfiguration:
    network: NetworkId = DEFAULT_NETWORK
    traffic_profile: TrafficProfile = DEFAULT_TRAFFIC_PROFILE
    controller_mode: ControllerMode = DEFAULT_CONTROLLER_MODE
    emergency_vehicles_enabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "traffic_profile": self.traffic_profile,
            "controller_mode": self.controller_mode,
            "emergency_vehicles_enabled": self.emergency_vehicles_enabled,
        }


def validate_configuration(
    *,
    network: str,
    traffic_profile: str,
    controller_mode: str,
    emergency_vehicles_enabled: bool,
) -> SimulationConfiguration:
    if network not in NETWORK_IDS:
        raise ValueError(
            f"unknown network '{network}'; expected one of: {', '.join(NETWORK_IDS)}"
        )
    if traffic_profile not in TRAFFIC_PROFILES:
        raise ValueError(
            "unknown traffic_profile "
            f"'{traffic_profile}'; expected one of: {', '.join(TRAFFIC_PROFILES)}"
        )
    if controller_mode not in CONTROLLER_MODES:
        raise ValueError(
            "unknown controller_mode "
            f"'{controller_mode}'; expected one of: {', '.join(CONTROLLER_MODES)}"
        )
    if type(emergency_vehicles_enabled) is not bool:
        raise ValueError("emergency_vehicles_enabled must be a boolean")
    return SimulationConfiguration(
        network=network,  # type: ignore[arg-type]
        traffic_profile=traffic_profile,  # type: ignore[arg-type]
        controller_mode=controller_mode,  # type: ignore[arg-type]
        emergency_vehicles_enabled=emergency_vehicles_enabled,
    )


def resolve_configuration(configuration: SimulationConfiguration) -> ScenarioDefinition:
    """Resolve one of the 36 public combinations to repository-owned SUMO files."""
    configuration = validate_configuration(**configuration.as_dict())
    if configuration.network == "single_intersection":
        config_name = {
            "normal": "normal",
            "rush_hour": "rush_hour",
            "unbalanced": "unbalanced",
        }[configuration.traffic_profile]
        if configuration.emergency_vehicles_enabled:
            config_name += "_emergency"
        return ScenarioDefinition(
            scenario_id=f"single_intersection_{configuration.traffic_profile}",
            display_name="Single Intersection",
            description="Synthetic four-approach signalized intersection.",
            config_path=_SINGLE / f"{config_name}.sumocfg",
            network_path=_SINGLE / "demo.net.xml",
            mapping_path=_SINGLE / "mappings.json",
            output_directory=_SINGLE / "output" / config_name,
            legacy_scenario_id="single-intersection-v1",
            coordinate_system="synthetic_cartesian_metres",
            seed=42,
            supports_adaptive_control=True,
            supports_emergency_priority=True,
            network=configuration.network,
            traffic_profile=configuration.traffic_profile,
            emergency_vehicles_enabled=configuration.emergency_vehicles_enabled,
        )

    config_name = configuration.traffic_profile
    if configuration.emergency_vehicles_enabled:
        config_name += "_emergency"
    return ScenarioDefinition(
        scenario_id=f"london_{configuration.traffic_profile}",
        display_name="London Network",
        description="Connected Oval/Kennington SUMO network.",
        config_path=_LONDON / "configs" / f"{config_name}.sumocfg",
        network_path=_LONDON / "london.net.xml",
        mapping_path=None,
        output_directory=_LONDON / "output" / config_name,
        legacy_scenario_id="london-oval-kennington-v1",
        coordinate_system="sumo_cartesian_metres_utm_zone_30",
        seed=20261113,
        supports_adaptive_control=True,
        adaptive_manifest_path=_LONDON / "network_gap.json",
        supports_emergency_priority=True,
        network=configuration.network,
        traffic_profile=configuration.traffic_profile,
        emergency_vehicles_enabled=configuration.emergency_vehicles_enabled,
    )


def list_configuration_options() -> dict[str, Any]:
    return {
        "networks": [
            {"id": "single_intersection", "display_name": "Single Intersection"},
            {"id": "london", "display_name": "London Network"},
        ],
        "traffic_profiles": [
            {"id": "normal", "display_name": "Normal"},
            {"id": "rush_hour", "display_name": "Rush Hour"},
            {"id": "unbalanced", "display_name": "Unbalanced"},
        ],
        "controller_modes": [
            {"id": "fixed_timing", "display_name": "Fixed Timing"},
            {"id": "adaptive_network", "display_name": "Adaptive Network"},
            {
                "id": "adaptive_emergency_priority",
                "display_name": "Adaptive Network + Emergency Priority",
            },
        ],
        "emergency_vehicle_options": [
            {"enabled": False, "display_name": "Disabled"},
            {"enabled": True, "display_name": "Enabled"},
        ],
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
            "supports_emergency_priority": scenario.supports_emergency_priority,
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
