"""Diagnostics contract: simile pileup and dialogue handling."""

import unittest

from prose_engine.diagnostics import ProseDiagnosticsAnalyzer


def warnings(text: str):
    return ProseDiagnosticsAnalyzer.analyze(text).warnings


class SimilePileupTests(unittest.TestCase):
    def test_three_comparisons_are_flagged(self):
        text = (
            "Her arms shimmered like liquid mercury and the seams popped like popcorn. "
            "Her backside swelled like a parade float. The tail dragged like a wet rope."
        )
        self.assertTrue(any("Simile pileup" in warning for warning in warnings(text)))

    def test_two_comparisons_are_not_flagged(self):
        text = (
            "Her arms shimmered like liquid mercury and the seams popped like popcorn. "
            "The dress gave at the seams and the room went quiet."
        )
        self.assertFalse(any("Simile pileup" in warning for warning in warnings(text)))

    def test_liking_something_is_not_a_simile(self):
        text = (
            "I like her. She likes me. They like it here. We like this house."
        )
        self.assertFalse(any("Simile pileup" in warning for warning in warnings(text)))

    def test_dialogue_is_not_judged_for_sensory_deficit(self):
        text = '- "I saw him at the store and I told him exactly what you said, and he laughed."'
        self.assertFalse(any("Sensory deficit" in warning for warning in warnings(text)))


if __name__ == "__main__":
    unittest.main()
