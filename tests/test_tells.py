"""Beat-tell contract: inline and standalone 'Beat.' are flagged, ordinary prose is not."""

import unittest

from prose_engine.screenplay import analyze_document


def kinds(paragraphs):
    return [tell.rule for tell in analyze_document(paragraphs)]


class BeatTellTests(unittest.TestCase):
    def test_standalone_beat_is_flagged(self):
        self.assertIn("BEAT_DIRECTION", kinds(["Beat.", "She sets the lipstick down."]))

    def test_inline_beat_is_flagged(self):
        self.assertIn("BEAT_DIRECTION", kinds(["Beat. She sets the lipstick down."]))

    def test_beat_inside_a_sentence_is_not_flagged(self):
        self.assertNotIn("BEAT_DIRECTION", kinds(["Her heart beat once, hard, and then went quiet."]))

    def test_beat_it_is_not_a_stage_direction(self):
        self.assertNotIn("BEAT_DIRECTION", kinds(["Beat it, she said, and meant it."]))


if __name__ == "__main__":
    unittest.main()
