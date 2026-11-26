"""Scene brief contracts."""

import tempfile
import unittest
from pathlib import Path

from prose_engine.voice.scene_brief import SceneBrief

TEXT = """Rainee sets the lipstick down.

- Absolutely not.

The gurgle answers.

- That was the sushi.

She walks a circle around the room."""


class SceneBriefTests(unittest.TestCase):
    def test_from_text_finds_dialogue(self):
        brief = SceneBrief.from_text(TEXT)
        self.assertEqual(len(brief.dialogue), 2)
        self.assertIn("Absolutely not", brief.dialogue[0].text)

    def test_kept_and_dropped(self):
        brief = SceneBrief.from_text(TEXT)
        brief.dialogue[1].keep = False
        self.assertEqual(len(brief.kept()), 1)
        self.assertEqual(len(brief.dropped()), 1)
        self.assertEqual(brief.frozen(), brief.kept())

    def test_prompt_block_lists_events_and_dialogue(self):
        brief = SceneBrief(events=["Rainee farts", "the dress bursts"], dialogue=SceneBrief.from_text(TEXT).dialogue)
        block = brief.prompt_block()
        self.assertIn("EVENTS", block)
        self.assertIn("KEEP VERBATIM", block)
        self.assertIn("REWRITE STRENGTH", block)

    def test_save_load_round_trip(self):
        brief = SceneBrief.from_text(TEXT, title="bathroom")
        brief.events = ["she farts"]
        brief.tone = "deadpan comedy"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "brief.json"
            brief.save(path)
            loaded = SceneBrief.load(path)
            self.assertEqual(loaded.title, "bathroom")
            self.assertEqual(loaded.events, ["she farts"])
            self.assertEqual(len(loaded.dialogue), 2)
            self.assertEqual(loaded.strength, brief.strength)
            self.assertEqual(loaded.tone, "deadpan comedy")


if __name__ == "__main__":
    unittest.main()
