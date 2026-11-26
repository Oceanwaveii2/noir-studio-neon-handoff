"""Slop detector contract."""

import unittest
from pathlib import Path

from prose_engine.voice.slop import FEATURES, SlopModel, features


class SlopTests(unittest.TestCase):
    def test_feature_vector(self):
        vector = features("She walks in. The room is cold, and the mirror holds her gaze.")
        self.assertEqual(len(vector), len(FEATURES))

    def test_model_load_and_score_range(self):
        path = Path("books/slop_model.json")
        if not path.is_file():
            self.skipTest("no slop model")
        model = SlopModel.load(path)
        for text in ("She sets the lipstick down.", "The air was thick with a sense of dread."):
            score = model.score(text)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_explain_returns_features(self):
        path = Path("books/slop_model.json")
        if not path.is_file():
            self.skipTest("no slop model")
        model = SlopModel.load(path)
        reasons = model.explain("In the mirror, her reflection wavered like a heat mirage.")
        self.assertTrue(all(name in FEATURES for name, _ in reasons))


if __name__ == "__main__":
    unittest.main()
