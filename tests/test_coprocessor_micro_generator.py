"""
Unit Tests for Local Micro-Dialogue & Sound-Effect Generator (Qwen3.5-9B / Qwen2.5).
Milestone CP-2: Rapid Micro-Dialogue & Sound-Effect Generator.
"""

import sys
import unittest
from unittest.mock import patch
from pathlib import Path

# Ensure repository root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prose_engine.coprocessor.micro_generator import (
    DialedCandidate,
    LocalMicroGenerator,
)


class TestLocalMicroGenerator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Unit tests exercise the actual offline fallback, even on hosts with weights installed.
        cls.generator = LocalMicroGenerator(lazy_load=True)

    def fallback(self, **request):
        with patch.object(self.generator, '_ensure_loaded', side_effect=OSError('Fixture: weights unavailable')):
            return self.generator.generate_dialogue_candidates(**request)

    def test_level_0_frozen_exact_match(self):
        """Level 0 must guarantee 0.0% word drift and exact byte-for-byte text equality."""
        raw_text = "Mom? Are you farting up there? It smells like a flower shop died!"
        candidates = self.generator.generate_dialogue_candidates(
            speaker="HALEY",
            raw_text=raw_text,
            raw_parenthetical="muffled",
            target_level=0,
        )

        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.influence_level, 0)
        self.assertEqual(c.dialed_text, raw_text)
        self.assertEqual(c.dialed_parenthetical, "muffled")
        self.assertEqual(c.word_drift_pct, 0.0)
        self.assertTrue(c.is_compliant)

    def test_level_20_subtle_inflection(self):
        """Level 20 must preserve spoken words (0% drift) and enrich delivery parentheticals."""
        raw_text = "Rainee! The clock is ticking! If we don't clear the turnpike before eight, the bridge toll is a nightmare!"
        candidates = self.generator.generate_dialogue_candidates(
            speaker="FRANCINE",
            raw_text=raw_text,
            raw_parenthetical="O.S.",
            target_level=20,
        )

        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.influence_level, 20)
        self.assertEqual(c.dialed_text, raw_text)
        self.assertEqual(c.word_drift_pct, 0.0)
        self.assertTrue(c.is_compliant)
        self.assertIn("urgency", c.dialed_parenthetical.lower())

    def test_level_50_balanced_blend_compliance(self):
        """Level 50 must fall between 15% and 67% drift and preserve core punchlines."""
        raw_text = "In a minute, Francine!"
        candidates = self.fallback(
            speaker="RAINEE",
            raw_text=raw_text,
            raw_parenthetical="straining",
            target_level=50,
            num_candidates=2,
        )

        self.assertGreaterEqual(len(candidates), 1)
        best = candidates[0]
        self.assertEqual(best.influence_level, 50)
        self.assertTrue(best.is_compliant)
        self.assertGreaterEqual(best.word_drift_pct, 15.0)
        self.assertLessEqual(best.word_drift_pct, 67.0)

    def test_level_75_radical_stylization_compliance(self):
        """Level 75 must fall between 45% and 98% drift."""
        raw_text = "Mom? Are you farting up there? It smells like a flower shop died!"
        candidates = self.fallback(
            speaker="HALEY",
            raw_text=raw_text,
            raw_parenthetical=None,
            target_level=75,
            num_candidates=2,
        )

        self.assertGreaterEqual(len(candidates), 1)
        best = candidates[0]
        self.assertEqual(best.influence_level, 75)
        self.assertTrue(best.is_compliant)
        self.assertGreaterEqual(best.word_drift_pct, 45.0)
        self.assertLessEqual(best.word_drift_pct, 98.0)

    def test_local_model_dialogue_when_requested(self):
        self.generator._ensure_loaded()
        self.assertTrue(self.generator.is_loaded)
        for tier, speaker, line in ((50, 'RAINEE', 'In a minute, Francine!'),
                                    (75, 'HALEY', 'Mom? Are you farting up there? It smells like a flower shop died!')):
            with self.subTest(tier=tier):
                candidates = self.generator.generate_dialogue_candidates(
                    speaker=speaker, raw_text=line, target_level=tier, num_candidates=2)
                self.assertTrue(candidates and candidates[0].is_compliant)
                self.assertTrue(self.generator.is_level_compliant(tier,candidates[0].word_drift_pct))

    def test_compliance_helper_bounds(self):
        """Audits the compliance boundary helper function."""
        self.assertTrue(self.generator.is_level_compliant(0, 0.0))
        self.assertFalse(self.generator.is_level_compliant(0, 5.0))

        self.assertTrue(self.generator.is_level_compliant(20, 0.0))
        self.assertTrue(self.generator.is_level_compliant(20, 4.0))
        self.assertFalse(self.generator.is_level_compliant(20, 10.0))

        self.assertTrue(self.generator.is_level_compliant(50, 35.0))
        self.assertFalse(self.generator.is_level_compliant(50, 10.0))
        self.assertFalse(self.generator.is_level_compliant(50, 70.0))

        self.assertTrue(self.generator.is_level_compliant(75, 60.0))
        self.assertFalse(self.generator.is_level_compliant(75, 30.0))
        self.assertFalse(self.generator.is_level_compliant(75, 99.0))

    def test_farce_onomatopoeia_sound_effects(self):
        """Generates stylized comic farce sound effects for canonical mechanics."""
        s1 = self.generator.generate_farce_onomatopoeia("acoustic_tile_amplification", "PFFFT")
        self.assertGreaterEqual(len(s1), 1)
        self.assertTrue(s1[0].startswith("*") and s1[0].endswith("*"))

        s2 = self.generator.generate_farce_onomatopoeia("bowl_water_vibration", "BLAAAART")
        self.assertGreaterEqual(len(s2), 1)
        self.assertTrue(s2[0].startswith("*") and s2[0].endswith("*"))


if __name__ == "__main__":
    unittest.main()
