"""Reference clips: load ingested dynamics and format them for prompts."""

import json
import tempfile
import unittest
from pathlib import Path

from prose_engine.voice.clips import format_clips, load_clips


class ClipTests(unittest.TestCase):
    def test_missing_clip_is_named(self):
        block = format_clips(["bridesmaids_bathroom"], directory=Path(tempfile.gettempdir()) / "nope")
        self.assertIn("not ingested yet", block)

    def test_ingested_clip_is_formatted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bridesmaids_bathroom.json"
            path.write_text(
                json.dumps(
                    {
                        "duration": 47.2,
                        "audio": {"peak_count": 6, "longest_silence": 2.1},
                        "transcript": [{"start": 3.4, "text": "Oh no."}],
                    }
                ),
                encoding="utf-8",
            )
            block = format_clips(["bridesmaids_bathroom"], directory=tmp)
            self.assertIn("47.2s", block)
            self.assertIn("6 energy peaks", block)
            self.assertIn("opens", block)

    def test_speech_profile_is_formatted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bridesmaids_bathroom.json"
            path.write_text(
                json.dumps(
                    {"speech": {"duration": 203.4, "cues": 94, "longest_gap": 11.4, "words_per_min": 328.2}}
                ),
                encoding="utf-8",
            )
            block = format_clips(["bridesmaids_bathroom"], directory=tmp)
            self.assertIn("94 speech cues", block)
            self.assertIn("11.4s", block)

    def test_load_clips_reads_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.json").write_text("{}", encoding="utf-8")
            self.assertIn("a", load_clips(tmp))


if __name__ == "__main__":
    unittest.main()
