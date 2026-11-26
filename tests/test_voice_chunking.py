"""Chunking contract: cues, parentheticals and dialogue stay together."""

import unittest

from prose_engine.voice.chunking import chunk_text, classify, label

TEXT = """INT. SMITH HOUSE — BEDROOM — 7:31 A.M.

Morning light lies across the carpet in long stripes.

RAINEE sits at the vanity.

**RAINEE**

*(to her reflection, warmly)*

- Okay, girl. Big day.

- We do not blink first.

She sets the brush down.

Then she hears it.
"""


class ChunkingTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify("INT. ROOM — DAY"), "scene")
        self.assertEqual(classify("**RAINEE**"), "cue")
        self.assertEqual(classify("*(to her reflection)*"), "parenthetical")
        self.assertEqual(classify("- Okay, girl."), "dialogue")
        self.assertEqual(classify("Morning light lies across the carpet."), "action")

    def test_dialogue_block_is_one_chunk(self):
        chunks = chunk_text(TEXT)
        dialogue = [chunk for chunk in chunks if "Okay, girl" in chunk]
        self.assertEqual(len(dialogue), 1)
        self.assertIn("**RAINEE**", dialogue[0])
        self.assertIn("*(to her reflection, warmly)*", dialogue[0])
        self.assertIn("We do not blink first", dialogue[0])

    def test_scene_heading_keeps_opening_action(self):
        chunks = chunk_text(TEXT)
        self.assertTrue(chunks[0].startswith("INT. SMITH HOUSE"))
        self.assertIn("Morning light", chunks[0])
        self.assertNotIn("RAINEE sits at the vanity", chunks[0])

    def test_no_chunk_is_a_bare_cue(self):
        chunks = chunk_text(TEXT)
        for chunk in chunks:
            self.assertNotEqual(chunk.strip(), "**RAINEE**")

    def test_short_action_lines_merge(self):
        chunks = chunk_text(TEXT)
        combined = [chunk for chunk in chunks if "Then she hears it." in chunk]
        self.assertEqual(len(combined), 1)
        self.assertIn("She sets the brush down.", combined[0])

    def test_label(self):
        chunks = chunk_text(TEXT)
        dialogue = next(chunk for chunk in chunks if "Okay, girl" in chunk)
        self.assertIn("RAINEE", label(dialogue))


if __name__ == "__main__":
    unittest.main()
