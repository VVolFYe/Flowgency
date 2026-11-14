import unittest

import numpy as np

from backend.vision.counting import VEHICLE_CLASSES
from backend.vision.eval_emergency import EmergencyVoter, pad_crop, touches_edge


class EmergencyVoterTest(unittest.TestCase):
    def test_flags_at_min_votes_and_threshold_then_stays_flagged(self) -> None:
        voter = EmergencyVoter(window=10, min_votes=5, thresh=0.6)
        for i, p in enumerate([0.9, 0.8, 0.2, 0.7]):
            self.assertFalse(voter.update(1, p, i))  # fewer than min_votes predictions
        self.assertTrue(voter.update(1, 0.1, 4.0))  # 3/5 = 0.6
        self.assertEqual(voter.flagged_at[1], 4.0)
        for i in range(20):
            self.assertTrue(voter.update(1, 0.0, 5 + i))  # sticky
        self.assertEqual((voter.positives(1), len(voter.history[1])), (0, 10))  # window capped

    def test_below_threshold_never_flags(self) -> None:
        voter = EmergencyVoter(window=10, min_votes=5, thresh=0.6)
        for i in range(10):
            voter.update(2, 0.55 if i % 2 else 0.4, i)  # 5/10 < 0.6
        self.assertFalse(voter.is_flagged(2))


class CropTest(unittest.TestCase):
    def test_touches_edge_within_one_percent(self) -> None:
        self.assertFalse(touches_edge((20, 10, 1260, 700), 1280, 720))  # 12.8 px / 7.2 px margins
        for bbox in ((12, 100, 200, 300), (100, 7, 200, 300), (100, 100, 1268, 300), (100, 100, 200, 713)):
            with self.subTest(bbox=bbox):
                self.assertTrue(touches_edge(bbox, 1280, 720))

    def test_pad_crop_pads_ten_percent_clamps_and_rejects_small(self) -> None:
        frame = np.zeros((100, 200, 3), np.uint8)
        self.assertEqual(pad_crop(frame, (50, 20, 150, 70)).shape[:2], (60, 120))  # 50x100 box + 10% per side
        self.assertEqual(pad_crop(frame, (0, 0, 100, 50)).shape[:2], (55, 110))  # clamped at the top-left corner
        self.assertIsNone(pad_crop(frame, (10, 10, 30, 30)))  # short side 24 px < 32


class VehicleClassesTest(unittest.TestCase):
    def test_bicycles_are_not_vehicles(self) -> None:
        self.assertNotIn("bicycle", VEHICLE_CLASSES)


if __name__ == "__main__":
    unittest.main()
