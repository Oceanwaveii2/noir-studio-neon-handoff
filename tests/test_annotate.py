"""Annotated document contract."""

import unittest

from tools.annotate import init_document, parse_document

SCENE = """# Show — Episode

> Preamble text.

INT. ROOM — DAY

Rainee stands at the mirror.

- Absolutely not.

EXT. PORCH — DAY

Ma Ma Ling waits.
"""


class AnnotateTests(unittest.TestCase):
    def test_init_creates_chunks(self):
        text = init_document(SCENE)
        self.assertIn("## CHUNK 1", text)
        self.assertIn("## CHUNK 2", text)
        self.assertIn("**NOTE:**", text)

    def test_parse_round_trip(self):
        text = init_document(SCENE)
        title, preamble, chunks = parse_document(text)
        self.assertEqual(len(chunks), 2)
        self.assertIn("INT. ROOM", chunks[0]["label"])
        self.assertIn("Rainee stands", chunks[0]["text"])
        self.assertIn("Ma Ma Ling", chunks[1]["text"])

    def test_note_is_parsed(self):
        text = init_document(SCENE).replace("**NOTE:**\n\n---", "**NOTE:**\ndarker, funnier\n\n---", 1)
        _, _, chunks = parse_document(text)
        self.assertEqual(chunks[0]["note"], "darker, funnier")

    def test_paragraph_level(self):
        text = init_document(SCENE, level="paragraph")
        _, _, chunks = parse_document(text)
        self.assertGreaterEqual(len(chunks), 4)


if __name__ == "__main__":
    unittest.main()
