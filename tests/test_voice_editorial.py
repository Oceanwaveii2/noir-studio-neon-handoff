"""Editorial notes: directions and rejected examples reach the prompt."""

import unittest
from pathlib import Path

from prose_engine.voice.editorial import EditorialNotes


class EditorialTests(unittest.TestCase):
    def setUp(self):
        self.notes = EditorialNotes.load(Path("books/editorial_notes.json"))

    def test_beats_load(self):
        self.assertGreaterEqual(len(self.notes.beats), 5)
        ids = {beat.id for beat in self.notes.beats}
        self.assertIn("bathroom", ids)

    def test_match_by_heading(self):
        beat = self.notes.for_text("INT. BATHROOM — CONTINUOUS\n\nRainee sits.")
        self.assertIsNotNone(beat)
        self.assertEqual(beat.id, "bathroom")

    def test_prompt_block_has_direction_and_avoid(self):
        block = self.notes.prompt_block("INT. RAINEE'S BEDROOM — CONTINUOUS\nRainee stands.")
        self.assertIn("SCENE DIRECTION", block)
        self.assertIn("NEVER WRITE LIKE THESE", block)
        self.assertIn("gurgle", block)

    def test_references_reach_the_prompt(self):
        block = self.notes.prompt_block("INT. BATHROOM — CONTINUOUS")
        self.assertIn("TONE REFERENCES", block)

    def test_unknown_text_has_no_block(self):
        self.assertEqual(self.notes.prompt_block("Anything at all."), "")


if __name__ == "__main__":
    unittest.main()
