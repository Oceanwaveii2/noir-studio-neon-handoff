"""
Unit Tests for Configurable Dialogue Influence Dial (0% - 75%).
Milestone M-PE5: Configurable Dialogue Influence Dial.
"""

import json
import unittest
from pathlib import Path

from prose_engine.dialogue_dial import (
    CharacterInfluenceSettings,
    DialTier,
    DialedDialogueLine,
    DialogueDialEngine,
    DialogueDriftViolation,
    compute_word_drift,
)


class TestDialogueDialEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.engine = DialogueDialEngine()
        cls.input_manifest_path = (
            cls.repo_root / "work" / "americandad" / "spring_breakup_gag_enriched_manifest.json"
        )
        cls.dialed_manifest_output_path = (
            cls.repo_root / "work" / "americandad" / "spring_breakup_dialed_manifest.json"
        )

    def test_settings_parsing(self):
        """Verifies parsing of single-integer and multi-character string specs."""
        s1 = CharacterInfluenceSettings.parse("50")
        self.assertEqual(s1.global_default, 50)
        self.assertEqual(s1.get_level("FRANCINE"), 50)

        s2 = CharacterInfluenceSettings.parse("Francine:0 Rainee:50 Haley:20")
        self.assertEqual(s2.global_default, 0)
        self.assertEqual(s2.get_level("Francine"), 0)
        self.assertEqual(s2.get_level("FRANCINE (O.S.)"), 0)
        self.assertEqual(s2.get_level("Rainee"), 50)
        self.assertEqual(s2.get_level("Haley"), 20)
        self.assertEqual(s2.get_level("Stan"), 0)

        s3 = CharacterInfluenceSettings.parse("Francine:0,Rainee:75,Haley:50")
        self.assertEqual(s3.get_level("Rainee"), 75)
        self.assertEqual(s3.get_level("Haley"), 50)

    def test_level_0_frozen_exact_byte_match(self):
        """Level 0 (Frozen) must enforce strictly 0.0% word drift and exact byte equality."""
        raw_text = "Mom? Are you farting up there? It smells like a flower shop died!"
        raw_paren = "muffled through the wooden door"

        dialed = self.engine.dial_line("HALEY", raw_text, raw_paren, level=0)
        self.assertEqual(dialed.influence_level, 0)
        self.assertEqual(dialed.dialed_text, raw_text)
        self.assertEqual(dialed.dialed_parenthetical, raw_paren)
        self.assertEqual(dialed.word_drift_pct, 0.0)

    def test_level_20_subtle_inflection(self):
        """Level 20 must preserve all spoken words (0% drift) while enriching delivery parentheticals."""
        raw_text = "Rainee! The clock is ticking! If we don't clear the turnpike before eight, the bridge toll is a nightmare!"
        raw_paren = "O.S."

        dialed = self.engine.dial_line("FRANCINE", raw_text, raw_paren, level=20)
        self.assertEqual(dialed.influence_level, 20)
        self.assertEqual(dialed.dialed_text, raw_text)
        self.assertNotEqual(dialed.dialed_parenthetical, raw_paren)
        self.assertIn("urgency", dialed.dialed_parenthetical.lower())
        self.assertEqual(dialed.word_drift_pct, 0.0)

    def test_level_50_balanced_blend_drift_bounds(self):
        """Level 50 must fall between 15% and 67% drift and preserve core punchlines."""
        raw_text = (
            "Oh God... oh sweet merciful heaven. It was that food truck burrito last night. "
            "Why do I ever let Jeff buy dinner? Who puts refried black beans, roasted garlic, "
            "and spicy street carnitas into one tortilla?"
        )
        dialed = self.engine.dial_line("RAINEE", raw_text, None, level=50)
        self.assertEqual(dialed.influence_level, 50)
        self.assertGreaterEqual(dialed.word_drift_pct, 15.0)
        self.assertLessEqual(dialed.word_drift_pct, 67.0)

        # Invariant: core punchlines preserved
        self.assertIn("burrito", dialed.dialed_text.lower())
        self.assertIn("beans", dialed.dialed_text.lower())
        self.assertIn("carnitas", dialed.dialed_text.lower())

    def test_level_75_radical_stylization_drift_bounds(self):
        """Level 75 must fall between 45% and 98% drift and reflect authorial lens dialect."""
        raw_text = "Mom? Are you farting up there? It smells like a flower shop died!"
        dialed = self.engine.dial_line("HALEY", raw_text, None, level=75)
        self.assertEqual(dialed.influence_level, 75)
        self.assertGreaterEqual(dialed.word_drift_pct, 45.0)
        self.assertLessEqual(dialed.word_drift_pct, 98.0)

        # Reflects authorial lens (funeral parlor / depth charges)
        self.assertTrue(
            "funeral" in dialed.dialed_text.lower() or "depth charges" in dialed.dialed_text.lower()
        )

    def test_per_character_configuration_routing(self):
        """Verifies multi-character routing where each speaker receives their configured dial."""
        settings = CharacterInfluenceSettings.parse("Francine:0 Rainee:50 Haley:20")

        f_raw = "Rainee, let's go! Okay, Rainee, let's get going! The girls' dinners are in the fridge. What is taking that foxy woman so long!"
        r_raw = "In a minute, Francine!"
        h_raw = "Ah, the ancient art of ancestral toot-massage. I am going to go see what Mom Two is up to."

        f_line = self.engine.dial_line("FRANCINE", f_raw, None, level=settings.get_level("FRANCINE"))
        r_line = self.engine.dial_line("RAINEE", r_raw, None, level=settings.get_level("RAINEE"))
        h_line = self.engine.dial_line("HALEY", h_raw, None, level=settings.get_level("HALEY"))

        self.assertEqual(f_line.influence_level, 0)
        self.assertEqual(f_line.word_drift_pct, 0.0)

        self.assertEqual(r_line.influence_level, 50)
        self.assertGreaterEqual(r_line.word_drift_pct, 15.0)

        self.assertEqual(h_line.influence_level, 20)
        self.assertEqual(h_line.word_drift_pct, 0.0)
        self.assertTrue(len(h_line.dialed_parenthetical) > 0)


    def test_audit_dialogue_drift_catches_violations(self):
        """Auditor must catch out-of-bounds drift on any line."""
        valid_lines = [
            DialedDialogueLine("FRANCINE", "Raw line", None, "Raw line", None, 0, 0.0, "lens"),
            DialedDialogueLine("RAINEE", "Raw line here", None, "New modified line here", None, 50, 30.0, "lens"),
        ]
        ok, violations = self.engine.audit_dialogue_drift(valid_lines)
        self.assertTrue(ok)
        self.assertEqual(len(violations), 0)

        invalid_lines = [
            # Level 0 but drift > 0
            DialedDialogueLine("FRANCINE", "Raw line", None, "Tampered line", None, 0, 25.0, "lens"),
        ]
        ok_bad, violations_bad = self.engine.audit_dialogue_drift(invalid_lines)
        self.assertFalse(ok_bad)
        self.assertEqual(len(violations_bad), 1)

    def test_dial_manifest_end_to_end(self):
        """End-to-end: Dial all 10 beats of Spring Breakup with mixed settings and verify audit PASS."""
        settings = CharacterInfluenceSettings.parse("Francine:0 Rainee:50 Haley:20")
        self.assertTrue(self.input_manifest_path.exists())

        res = self.engine.dial_manifest(
            manifest_path=self.input_manifest_path,
            settings=settings,
            output_path=self.dialed_manifest_output_path,
        )

        self.assertEqual(res["total_dialed_lines"], 17)
        self.assertTrue(self.dialed_manifest_output_path.exists())

        # Collect all dialed lines
        all_lines = []
        for b in res["beats"].values():
            for l in b.get("dialed_dialogue", []):
                all_lines.append(
                    DialedDialogueLine(
                        speaker=l["speaker"],
                        raw_text=l["raw_text"],
                        raw_parenthetical=l.get("raw_parenthetical"),
                        dialed_text=l["dialed_text"],
                        dialed_parenthetical=l.get("dialed_parenthetical"),
                        influence_level=l["influence_level"],
                        word_drift_pct=l["word_drift_pct"],
                        character_lens=l["character_lens"],
                    )
                )

        ok, violations = self.engine.audit_dialogue_drift(all_lines)
        self.assertTrue(ok, f"Violations found: {violations}")
        self.assertEqual(len(violations), 0)


if __name__ == "__main__":
    unittest.main()
