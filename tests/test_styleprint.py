"""Stylometric fingerprint contract."""

import unittest

import numpy as np

from prose_engine.styleprint import NAMES, distance, fingerprint


class StyleprintTests(unittest.TestCase):
    def test_fingerprint_matches_feature_names(self):
        vector = fingerprint("She walks in. The room is cold, and the door clicks shut.")
        self.assertEqual(len(vector), len(NAMES))
        self.assertTrue(np.all(np.isfinite(vector)))

    def test_identical_profiles_have_zero_distance(self):
        model = {"mean": [0.0] * len(NAMES), "sd": [1.0] * len(NAMES)}
        vector = np.zeros(len(NAMES))
        self.assertAlmostEqual(distance(vector, model), 0.0, places=6)

    def test_outliers_are_capped(self):
        model = {"mean": [0.0] * len(NAMES), "sd": [1.0] * len(NAMES)}
        extreme = np.full(len(NAMES), 1000.0)
        self.assertLessEqual(distance(extreme, model), 3.0 + 1e-6)

    def test_different_rhythm_changes_the_fingerprint(self):
        short = "She stops. He turns. The door clicks. Nobody speaks."
        long = (
            "She stops in the doorway and considers the room for a long moment before she finally "
            "turns to him and says that it is over."
        )
        self.assertFalse(np.allclose(fingerprint(short), fingerprint(long)))


if __name__ == "__main__":
    unittest.main()
