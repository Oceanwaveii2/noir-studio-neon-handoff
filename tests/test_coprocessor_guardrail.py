"""
Unit Tests for Real-Time 6-Gram Plagiarism & Neural Slop Coprocessor.
Milestone CP-3: Real-Time 6-Gram Plagiarism & Neural Slop Coprocessor.
"""

import sys
import unittest
from pathlib import Path

# Ensure repository root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prose_engine.coprocessor.guardrail import (
    GuardrailAuditReport,
    GuardrailCoprocessor,
)
from prose_engine.linter import AntiAILinter


class TestGuardrailCoprocessor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guardrail = GuardrailCoprocessor()

    def test_clean_prose_passes_guardrails(self):
        """Lush, varied prose free of 6-grams and AI tells must pass all audit gates."""
        clean_prose = """
The tiles hummed. In the narrow upstairs powder room, Francine adjusted her silk robe, her fingertips damp against the mahogany trim of the vanity mirror.
Down below, the refrigerator motor kicked into gear with a metallic shudder.
She took a deep breath, listening to the muffled splash of water from the marina slip two blocks away.
The air in the hallway smelled faintly of lemon wax and yesterday's chlorine.
"""
        report = self.guardrail.audit_text(
            clean_prose,
            reference_passages=["A completely unrelated passage about mountain climbing in winter storms."],
            burstiness_threshold=3.0,
        )

        self.assertTrue(report.passed)
        self.assertTrue(report.is_clean_of_plagiarism)
        self.assertTrue(report.is_clean_of_ai_tells)
        self.assertTrue(report.burstiness_passed)
        self.assertEqual(len(report.plagiarism_issues), 0)
        self.assertEqual(len(report.ai_tell_violations), 0)

    def test_reference_matches_are_non_blocking_for_storytelling(self):
        """Reference n-gram matches are purely informational and do not block storytelling."""
        reference = [
            "the velvet dressing gown slipped slowly across the polished marble floor of the penthouse"
        ]
        borrowed_prose = """
The velvet dressing gown slipped slowly across the polished marble floor of the penthouse suite.
Wind shrieked.
Outside, through the shattered leaded glass of the upper conservatory, the storm rattled the iron shutters with terrifying, unrelenting violence until the foundation groaned.
"""

        # By default, storytelling is NOT blocked by reference n-grams
        report = self.guardrail.audit_text(
            borrowed_prose,
            reference_passages=reference,
            burstiness_threshold=3.0,
        )

        self.assertTrue(report.passed)
        self.assertFalse(report.is_clean_of_plagiarism)
        self.assertGreater(len(report.informational_reference_matches), 0)

        # Only blocks if explicitly requested
        strict_report = self.guardrail.audit_text(
            borrowed_prose,
            reference_passages=reference,
            burstiness_threshold=3.0,
            enforce_plagiarism_blocking=True,
        )
        self.assertFalse(strict_report.passed)

    def test_ai_binary_contrast_and_transition_detection(self):
        """Detects banned mechanical AI binary contrasts and essayistic transitions."""
        slop_prose = """
It was less a celebration and more a calculated domestic maneuver.
Because of this, the tension in the bathroom continued to escalate steadily.
Francine paused, hesitated, and considered her options carefully before speaking.
"""
        report = self.guardrail.audit_text(slop_prose, burstiness_threshold=1.0)

        self.assertFalse(report.passed)
        self.assertFalse(report.is_clean_of_ai_tells)
        # Should flag binary contrast ('less a X and more a Y') and transition ('Because of this')
        categories = [issue for issue in report.ai_tell_violations]
        self.assertTrue(any("binary_contrast" in c for c in categories))
        self.assertTrue(any("essayistic_transition" in c for c in categories))

    def test_romance_melodrama_cliche_detection(self):
        """Detects blacklisted romance melodrama tropes."""
        melodrama_prose = """
Francine stared at the mirror with a white-knuckles grip on the porcelain edge.
A pale blush crept up her neck as a primal panic seized her chest.
"""
        report = self.guardrail.audit_text(melodrama_prose)

        self.assertFalse(report.passed)
        self.assertFalse(report.is_clean_of_ai_tells)
        self.assertTrue(any("romance_cliche" in c for c in report.ai_tell_violations))

    def test_burstiness_failure_on_monotonous_cadence(self):
        """Flags monotonous prose where all sentences have nearly identical lengths."""
        monotonous_prose = """
Francine walked slowly to the door.
She turned the shiny golden knob.
The wooden floor creaked very loudly.
She listened to the quiet room.
"""
        report = self.guardrail.audit_text(monotonous_prose, burstiness_threshold=4.0)

        self.assertFalse(report.passed)
        self.assertFalse(report.burstiness_passed)
        self.assertLess(report.burstiness_score, 4.0)

    def test_report_serialization_to_dict(self):
        """Audit report serializes cleanly to JSON-compatible dictionary."""
        report = self.guardrail.audit_text("Short sample text.")
        data = report.to_dict()
        self.assertIn("passed", data)
        self.assertIn("is_clean_of_plagiarism", data)
        self.assertIn("is_clean_of_ai_tells", data)
        self.assertIn("burstiness_passed", data)
        self.assertIn("burstiness_score", data)

    def test_ontological_rules_and_morph_restrictions_screening(self):
        """Milestone O-4: Tests real-time screening of negative ontology rules and morph matrix."""
        # 1. Hallucinating a father or patriarchal figure
        bad_father = "Rainee turned to Haley. 'Your father taught you that before he left.'"
        rules = [{"id": "no_father", "pattern": r"\b(father|Dad|Daddy)\b", "why": "Zero patriarchal lineage."}]
        report = self.guardrail.audit_text(bad_father, ontology_negative_rules=rules)
        self.assertFalse(report.passed)
        self.assertFalse(report.is_clean_of_ontological_breaches)
        self.assertTrue(any("ONTOLOGY_BREACH" in v for v in report.ontological_violations))

        # 2. Morph permission violation on Haley
        bad_morph = "Haley gasped and morphed into a silver fox."
        perms = {"haley": False, "rainee": True}
        report_morph = self.guardrail.audit_text(bad_morph, character_morph_permissions=perms)
        self.assertFalse(report_morph.passed)
        self.assertFalse(report_morph.is_clean_of_ontological_breaches)
        self.assertTrue(any("MORPH_BREACH" in v for v in report_morph.ontological_violations))

        # 3. Permitted morph on Rainee
        good_morph = "Rainee shifted her form effortlessly into the emerald glamour gown."
        report_rainee = self.guardrail.audit_text(good_morph, character_morph_permissions=perms, burstiness_threshold=0.0)
        self.assertTrue(report_rainee.is_clean_of_ontological_breaches)
        self.assertEqual(len(report_rainee.ontological_violations), 0)


if __name__ == "__main__":
    unittest.main()
