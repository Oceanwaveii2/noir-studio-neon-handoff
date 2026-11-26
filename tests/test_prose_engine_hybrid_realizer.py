"""
Unit Tests for Script-Novel Hybrid Realizer & Anti-AI-ism Linter.
Milestone M-PE6: Script-Novel Hybrid Realizer & Anti-AI-ism Linter.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from prose_engine.hybrid_realizer import (
    SCENE_METADATA,
    ScriptNovelHybridRealizer,
)
from prose_engine.linter import (
    AntiAILinter,
    AntiAILinterError,
    LinterReport,
)


class TestAntiAILinter(unittest.TestCase):
    def setUp(self):
        self.linter = AntiAILinter()

    def test_clean_text_passes_with_sufficient_burstiness(self):
        """Natural human prose with high length variation should pass with zero violations."""
        prose = (
            "She stood by the window. Rain lashed against the glass with relentless fury. "
            "Her tea had long since grown cold, but she didn't care. "
            "Downstairs, the front door rattled on its hinges. "
            "Who could possibly be arriving at this ungodly hour of the night? Nobody she wanted to see. "
            "She turned slowly, pacing across the hardwood toward the grandfather clock that ticked in the corner."
        )
        report = self.linter.lint(prose, burstiness_threshold=3.0)
        self.assertEqual(report.total_violations, 0)
        self.assertTrue(report.burstiness_passed)
        self.assertTrue(report.passed)

    def test_binary_contrast_detection(self):
        """Detects 'less X and more Y' and 'not so much X as Y'."""
        bad_text = "His response was less an apology and more a declaration of war across the kitchen."
        report = self.linter.lint(bad_text)
        self.assertFalse(report.passed)
        self.assertIn("binary_contrast", report.summary)
        self.assertGreater(report.summary["binary_contrast"], 0)

        with self.assertRaises(AntiAILinterError):
            self.linter.assert_clean(bad_text)

    def test_essayistic_transition_detection(self):
        """Detects 'Because of this', 'Due to this', etc."""
        bad_text = "Because of this, the entire family decided to cancel their summer trip to the shore."
        report = self.linter.lint(bad_text)
        self.assertFalse(report.passed)
        self.assertIn("essayistic_transition", report.summary)
        self.assertGreater(report.summary["essayistic_transition"], 0)

    def test_tripartite_verbs_detection(self):
        """Detects symmetrical 3-verb serial lists."""
        bad_text = "He gasped, stumbled, and collapsed onto the living room carpet."
        report = self.linter.lint(bad_text)
        self.assertFalse(report.passed)
        self.assertIn("tripartite_verbs", report.summary)
        self.assertGreater(report.summary["tripartite_verbs"], 0)

    def test_romance_cliches_detection(self):
        """Detects stock romance melodrama tropes like 'primal panic' and 'quivering jaw'."""
        bad_text = "A wave of primal panic seized her as her quivering jaw gave away her guilt."
        report = self.linter.lint(bad_text)
        self.assertFalse(report.passed)
        self.assertIn("romance_cliche", report.summary)
        self.assertGreaterEqual(report.summary["romance_cliche"], 2)

    def test_weak_participial_tail_detection(self):
        """Detects trailing dangling participles like ', leaving the room in silence.'"""
        bad_text = "She slammed the heavy oak door shut, leaving the kitchen in total silence."
        report = self.linter.lint(bad_text)
        self.assertFalse(report.passed)
        self.assertIn("weak_participial_tail", report.summary)
        self.assertGreater(report.summary["weak_participial_tail"], 0)

    def test_burstiness_metric(self):
        """Monotonous robotic sentence lengths fail the burstiness threshold."""
        # Sentences with identical 5-word counts:
        monotonous = (
            "She walked to the door. "
            "He looked at the floor. "
            "They saw the white cat. "
            "We heard the loud sound. "
            "She held the big key. "
        )
        report = self.linter.lint(monotonous, burstiness_threshold=4.0)
        self.assertEqual(report.total_violations, 0)
        self.assertFalse(report.burstiness_passed)
        self.assertFalse(report.passed)
        self.assertLess(report.burstiness_score, 1.0)


class TestScriptNovelHybridRealizer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.realizer = ScriptNovelHybridRealizer()
        cls.dialed_manifest_path = (
            cls.repo_root / "work" / "americandad" / "spring_breakup_dialed_manifest.json"
        )
        output = tempfile.TemporaryDirectory()
        cls.addClassCleanup(output.cleanup)
        cls.output_manuscript_path = Path(output.name) / "generated-draft.md"

    def test_dialogue_block_formatting(self):
        """Verifies clean script-style dialogue turn formatting."""
        line_with_paren = {
            "speaker": "FRANCINE",
            "dialed_text": "Rainee, let's go!",
            "dialed_parenthetical": "O.S.",
        }
        formatted = self.realizer.format_dialogue_block(line_with_paren)
        self.assertIn("FRANCINE", formatted)
        self.assertIn("(O.S.)", formatted)
        self.assertIn("Rainee, let's go!", formatted)

        line_no_paren = {
            "speaker": "HALEY",
            "dialed_text": "Did you hear that?",
        }
        formatted_no_paren = self.realizer.format_dialogue_block(line_no_paren)
        self.assertIn("HALEY", formatted_no_paren)
        self.assertNotIn("()", formatted_no_paren)
        self.assertIn("Did you hear that?", formatted_no_paren)

    def test_realize_manifest_end_to_end(self):
        """Assembles hybrid novel from dialed manifest and verifies structure, linter, and gags."""
        manuscript = self.realizer.realize_manifest(
            self.dialed_manifest_path,
            output_path=self.output_manuscript_path,
        )

        self.assertTrue(self.output_manuscript_path.exists())
        self.assertTrue(self.output_manuscript_path.read_text(encoding="utf-8").startswith(
            "<!-- Generated draft: no author review or approved revision. -->"))
        self.assertGreater(len(manuscript), 5000)

        # Invariant: Contains all 3 canonical scene headers
        for scene_id, meta in SCENE_METADATA.items():
            self.assertIn(meta["heading"], manuscript)

        # Invariant: Passes Anti-AI Linter with zero violations and burstiness >= 4.0
        report = self.realizer.linter.lint(manuscript, burstiness_threshold=4.0)
        self.assertEqual(report.total_violations, 0, f"Linter violations found: {report.violations}")
        self.assertTrue(report.burstiness_passed)
        self.assertGreaterEqual(report.burstiness_score, 4.0)

        # Invariant: Verifies all 6 farce mechanics from M-PE4
        gag_report = self.realizer.gag_injector.audit_scene(manuscript)
        self.assertEqual(gag_report.detected_count, 6)
        self.assertTrue(gag_report.passed_threshold)

        # Invariant: Dialogue lines present
        self.assertIn("FRANCINE", manuscript)
        self.assertIn("RAINEE", manuscript)
        self.assertIn("HALEY", manuscript)
        self.assertIn("burrito", manuscript.lower())

    def test_cli_execution(self):
        """Verifies python -m prose_engine.hybrid_realizer CLI exit code 0."""
        cmd = [
            sys.executable,
            "-m",
            "prose_engine.hybrid_realizer",
            "--manifest",
            str(self.dialed_manifest_path),
            "--out",
            str(self.output_manuscript_path),
        ]
        res = subprocess.run(
            cmd,
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, f"CLI stderr: {res.stderr}")
        self.assertIn("Synthesis complete!", res.stdout)
        self.assertIn("Linter: PASS", res.stdout)
        self.assertIn("Gag Audit: PASS", res.stdout)


if __name__ == "__main__":
    unittest.main()
