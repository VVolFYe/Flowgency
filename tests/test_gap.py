"""Regressions for the green service-gap predicate."""

import unittest

from backend.controller.gap import has_service_gap


class GapTests(unittest.TestCase):
    def vehicle(self, link, distance, speed=0):
        return {"link_index": link, "distance_m": distance, "speed_mps": speed}

    def test_empty_observations_do_not_release_green(self):
        self.assertFalse(has_service_gap("Gr", []))

    def test_competing_queue_with_empty_green(self):
        self.assertTrue(has_service_gap("Gr", [self.vehicle(1, 10)]))

    def test_nearby_served_vehicle_protects_green(self):
        self.assertFalse(has_service_gap(
            "Gr", [self.vehicle(1, 10), self.vehicle(0, 10)]
        ))

    def test_fast_approaching_vehicle_protects_green(self):
        self.assertFalse(has_service_gap(
            "Gr", [self.vehicle(1, 10), self.vehicle(0, 50, 15)]
        ))

    def test_distant_red_vehicle_does_not_request_release(self):
        self.assertFalse(has_service_gap("Gr", [self.vehicle(1, 100)]))
