"""Validation and file resolution for all public simulation combinations."""

from __future__ import annotations

import itertools
import unittest

from backend.simulation.scenarios import (
    CONTROLLER_MODES,
    NETWORK_IDS,
    SimulationConfiguration,
    TRAFFIC_PROFILES,
    resolve_configuration,
    validate_configuration,
)


class SimulationConfigurationTests(unittest.TestCase):
    def test_all_36_combinations_resolve_to_real_sumo_sources(self) -> None:
        combinations = list(
            itertools.product(
                NETWORK_IDS, TRAFFIC_PROFILES, CONTROLLER_MODES, (False, True)
            )
        )
        self.assertEqual(len(combinations), 36)
        for network, profile, controller, emergency_enabled in combinations:
            with self.subTest(
                network=network,
                profile=profile,
                controller=controller,
                emergency=emergency_enabled,
            ):
                configuration = validate_configuration(
                    network=network,
                    traffic_profile=profile,
                    controller_mode=controller,
                    emergency_vehicles_enabled=emergency_enabled,
                )
                scenario = resolve_configuration(configuration)
                self.assertTrue(scenario.network_path.is_file())
                self.assertTrue(scenario.config_path.is_file())
                self.assertEqual(scenario.network, network)
                self.assertEqual(scenario.traffic_profile, profile)
                self.assertEqual(
                    scenario.emergency_vehicles_enabled, emergency_enabled
                )

    def test_unknown_ids_and_non_boolean_emergency_are_rejected(self) -> None:
        base = dict(
            network="single_intersection",
            traffic_profile="normal",
            controller_mode="fixed_timing",
            emergency_vehicles_enabled=False,
        )
        for field, value in (
            ("network", "unknown"),
            ("traffic_profile", "weekend"),
            ("controller_mode", "magic"),
            ("emergency_vehicles_enabled", 1),
        ):
            invalid = {**base, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_configuration(**invalid)

        with self.assertRaises(ValueError):
            resolve_configuration(
                # Runtime validation also protects non-Pydantic callers.
                SimulationConfiguration(network="unknown")  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
