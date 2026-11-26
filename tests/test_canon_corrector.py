"""Tests for deterministic world-rule, character-profile, and mind auto-correction."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from prose_engine.canon_corrector import auto_correct_canon
from prose_engine.scoped_service import execute_scoped
from prose_engine.voice.world_state import WorldState
from story_graph.episode_timeline import TimelineStore


class CanonCorrectorTests(unittest.TestCase):
    def test_mind_surname_and_relationship_auto_corrections_in_spring_break(self):
        world = WorldState.load()
        sample = (
            "INT. SMITH KITCHEN — 7:31 A.M.\n\n"
            "Francine Smith set the mug down in the Smith house.\n"
            '"Haley," Rainee said, "just because you inherited your husband Jeff\'s ass '
            'is no reason to be catty."\n'
            "Francine's husband walked in, and Rainee's husband waited outside.\n"
        )
        res = auto_correct_canon(sample, apply=True, world_state=world, episode_id="spring-break")
        self.assertGreaterEqual(res.applied_count, 5)
        self.assertIn("INT. LING KITCHEN — 7:31 A.M.", res.corrected_text)
        self.assertIn("Francine Ling set the mug down in the Ling house.", res.corrected_text)
        self.assertIn("inherited your boyfriend Jeff's ass", res.corrected_text)
        self.assertIn("Francine's wife walked in", res.corrected_text)
        self.assertIn("Rainee's wife waited outside", res.corrected_text)
        self.assertEqual(res.remaining_violations, ())

    def test_preserves_hot_scoomp_married_epoch_and_valid_negations(self):
        married_text = (
            "Haley avoided her husband Jeff before walking into the Ling living room.\n"
            "Francine never took the Smith name.\n"
            "In the American Dad broadcast show, Mrs. Smith lived there.\n"
        )
        res = auto_correct_canon(married_text, apply=True, episode_id="hot-scoomp")
        self.assertEqual(res.applied_count, 0)
        self.assertEqual(res.corrected_text, married_text)
        self.assertEqual(res.remaining_violations, ())

    def test_respects_protected_ranges(self):
        sample = "Francine Smith waited in the Smith Kitchen."
        # Lock only the first "Francine Smith" span; still repair "Smith Kitchen".
        res = auto_correct_canon(
            sample,
            apply=True,
            episode_id="spring-break",
            protected_ranges=((0, 14),),
        )
        self.assertEqual(res.corrected_text, "Francine Smith waited in the Ling Kitchen.")

    def test_scoped_validate_and_check_canon_cli_expose_fixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "timeline.sqlite"
            store = TimelineStore(db, project_id="p", universe_id="u")
            store.add_starter_cards()
            store.save("spring-break", 0, script="A quiet room.", source_name="fixture")
            val = execute_scoped(
                store,
                "validate",
                {
                    "episode": "spring-break",
                    "beat": 1,
                    "revision": 1,
                    "start": 0,
                    "end": 13,
                    "project": "p",
                    "universe": "u",
                    "text": "Haley waited for her husband Jeff in the Smith Kitchen.",
                },
            )
            self.assertGreaterEqual(len(val["suggested_corrections"]), 2)
            self.assertEqual(
                val["auto_corrected_text"],
                "Haley waited for her boyfriend Jeff in the Ling Kitchen.",
            )

            manuscript = root / "manuscript.md"
            manuscript.write_text('Rainee smirked, "Look at your husband Jeff."\n', encoding="utf-8")
            fix_run = subprocess.run(
                [sys.executable, "-B", "tools/check_canon.py", "--file", str(manuscript), "--fix"],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(fix_run.returncode, 0, fix_run.stdout + fix_run.stderr)
            self.assertIn("boyfriend Jeff", manuscript.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
