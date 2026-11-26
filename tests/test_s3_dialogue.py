"""S3: dialogue must survive correction byte-for-byte."""

import unittest
from pathlib import Path

from prose_engine.conditioner import apply_proposals, is_dialogue, plan_conditioning, paragraph_spans
from prose_engine.providers import create_prose_provider
from prose_engine.style_engine import STANDARD_DRAMATIC

SCENE = Path("work/americandad/start_scene_annotated.md")


class DialogueFreezeTests(unittest.TestCase):
    def test_dialogue_paragraphs_are_unchanged(self):
        text = SCENE.read_text(encoding="utf-8")
        provider = create_prose_provider("mock")
        proposals = plan_conditioning(text, provider, STANDARD_DRAMATIC)
        updated, _applied = apply_proposals(text, proposals)
        for start, end in paragraph_spans(text):
            paragraph = text[start:end].strip()
            if is_dialogue(paragraph):
                self.assertIn(paragraph, updated, "dialogue paragraph was modified")


if __name__ == "__main__":
    unittest.main()
