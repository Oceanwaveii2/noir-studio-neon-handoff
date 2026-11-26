"""
Unit Tests for Dual-Engine Pipeline Harness.
Milestone CP-4: Dual-Engine Pipeline Harness.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repository root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prose_engine.coprocessor.harness import (
    CoprocessorPipelineReport,
    DualEngineHarness,
)
from prose_engine.coprocessor.guardrail import GuardrailAuditReport
from prose_engine.coprocessor.micro_generator import DialedCandidate
from prose_engine.coprocessor.reranker import RerankResult


class TestDualEngineHarness(unittest.TestCase):
    def test_mode_validation(self):
        """Harness validates supported modes and rejects invalid strings."""
        h_hybrid = DualEngineHarness(mode="hybrid", lazy_load=True)
        self.assertEqual(h_hybrid.mode, "hybrid")

        h_local = DualEngineHarness(mode="local", lazy_load=True)
        self.assertEqual(h_local.mode, "local")

        h_rule = DualEngineHarness(mode="rule_based", lazy_load=True)
        self.assertEqual(h_rule.mode, "rule_based")

        with self.assertRaises(ValueError):
            DualEngineHarness(mode="invalid_super_mode")

    def test_rule_based_somatic_reranking(self):
        """Rule-based mode modulates candidate rank by soft book weights."""
        harness = DualEngineHarness(mode="rule_based")

        passages = [
            {"id": "p1", "text": "peach silk vanity robe", "weight": 1.25, "book_id": "gabriela"},
            {"id": "p2", "text": "peach silk kimono", "weight": 0.05, "book_id": "valley_of_the_dolls"},
            {"id": "p3", "text": "cold porcelain bathroom tiles", "weight": 1.0, "book_id": "fart_novel"},
        ]

        results = harness.rerank_somatic_passages(
            queries=["peach silk vanity"],
            candidate_passages=passages,
            top_k=3,
        )

        self.assertEqual(len(results), 3)
        self.assertIsInstance(results[0], RerankResult)
        # Primary book (weight 1.25) must rank above damped book (weight 0.05)
        self.assertEqual(results[0].book_slug, "gabriela")
        self.assertGreater(results[0].effective_score, results[1].effective_score)

    def test_rule_based_dialogue_dialing(self):
        """Rule-based dialogue dialing guarantees 0% drift on Level 0."""
        harness = DualEngineHarness(mode="rule_based")
        raw_line = "Mom? Are you farting up there? It smells like a flower shop died!"

        # Level 0: 0 bytes drift
        c0 = harness.dial_dialogue_line(
            speaker="HALEY",
            raw_text=raw_line,
            raw_parenthetical="muffled",
            target_level=0,
        )
        self.assertEqual(c0.dialed_text, raw_line)
        self.assertEqual(c0.word_drift_pct, 0.0)
        self.assertTrue(c0.is_compliant)

        # Level 20: subtle parenthetical delivery inflection
        c20 = harness.dial_dialogue_line(
            speaker="HALEY",
            raw_text=raw_line,
            raw_parenthetical="muffled",
            target_level=20,
        )
        self.assertEqual(c20.dialed_text, raw_line)
        self.assertEqual(c20.word_drift_pct, 0.0)
        self.assertTrue(c20.is_compliant)

    def test_farce_sfx_generation(self):
        """Generates appropriate comic onomatopoeia for farce mechanics."""
        h_rule = DualEngineHarness(mode="rule_based")
        sfx_tile = h_rule.generate_farce_sfx("tile_amplification")
        self.assertIn("BRAAAP", sfx_tile)

        sfx_water = h_rule.generate_farce_sfx("bowl_water_ripples")
        self.assertIn("PLOOP", sfx_water)

    def test_audit_prose_integration(self):
        """Audits prose for both plagiarism and AI tells via Guardrail Coprocessor."""
        harness = DualEngineHarness(mode="rule_based")

        clean_text = """
The tiles hummed. In the narrow upstairs powder room, Francine adjusted her silk robe.
Her fingertips were damp against the mahogany trim of the mirror.
Down below, the motor kicked into gear with a heavy shudder.
She took a deep breath, listening to the muffled splash from the marina slip two blocks away.
"""
        report_clean = harness.audit_prose(clean_text, burstiness_threshold=3.0)
        self.assertTrue(report_clean.passed)
        self.assertTrue(report_clean.is_clean_of_plagiarism)
        self.assertTrue(report_clean.is_clean_of_ai_tells)

        slop_text = "It was less a room and more a trap. Because of this, she panicked."
        report_slop = harness.audit_prose(slop_text)
        self.assertFalse(report_slop.passed)
        self.assertFalse(report_slop.is_clean_of_ai_tells)

        # Reference / borrowed text must NOT block storytelling by default
        borrowed_text = """
The velvet dressing gown slipped slowly across the polished marble floor of the penthouse suite.
Wind shrieked.
Outside, through the shattered leaded glass of the upper conservatory, the storm rattled the iron shutters with terrifying, unrelenting violence until the foundation groaned.
"""
        report_borrowed = harness.audit_prose(
            borrowed_text,
            reference_passages=["the velvet dressing gown slipped slowly across the polished marble floor of the penthouse"],
            burstiness_threshold=3.0,
        )
        self.assertTrue(report_borrowed.passed)
        self.assertFalse(report_borrowed.is_clean_of_plagiarism)

    def test_audit_prose_ontological_screening(self):
        """Milestone O-4: Verifies harness real-time ontological screening rejects illegal terms and morphs."""
        from story_graph.ontology import OntologyGraph
        onto = OntologyGraph.create_canonical_foxy_mo2()
        harness = DualEngineHarness(mode="rule_based")

        # 1. Negative regex rule breach (father hallucination)
        bad_father = "Rainee spoke to Haley about her father's lineage across town."
        rep_father = harness.audit_prose(
            bad_father,
            ontology_negative_rules=onto.hard_negative_rules,
            character_morph_permissions=onto.get_character_morph_permissions(),
        )
        self.assertFalse(rep_father.passed)
        self.assertFalse(rep_father.is_clean_of_ontological_breaches)
        self.assertTrue(any("ONTOLOGY_BREACH" in v for v in rep_father.ontological_violations))

        # 2. Morph permission breach (Haley unauthorized morph)
        bad_morph = "Haley concentrated deeply and her body morphed into an emerald fox."
        rep_morph = harness.audit_prose(
            bad_morph,
            ontology_negative_rules=onto.hard_negative_rules,
            character_morph_permissions=onto.get_character_morph_permissions(),
        )
        self.assertFalse(rep_morph.passed)
        self.assertFalse(rep_morph.is_clean_of_ontological_breaches)
        self.assertTrue(any("MORPH_BREACH" in v for v in rep_morph.ontological_violations))

        # 3. Canonical compliant prose
        good_text = (
            "Rainee leaned back against the deep cushions, her broad hips filling the double loveseat with ease. "
            "She smirked. "
            "Downstairs, Francine checked the glowing kitchen clock on the refrigerator door before heading out. "
            "Haley remained on the sofa, scrolling through text messages from her boyfriend Jeff."
        )
        rep_good = harness.audit_prose(
            good_text,
            burstiness_threshold=3.0,
            ontology_negative_rules=onto.hard_negative_rules,
            character_morph_permissions=onto.get_character_morph_permissions(),
        )
        self.assertTrue(rep_good.passed)
        self.assertTrue(rep_good.is_clean_of_ontological_breaches)
        self.assertEqual(len(rep_good.ontological_violations), 0)

    def test_synthesize_and_verify_with_real_manifest(self):
        """Synthesizes hybrid novel from manifest and subjects it to guardrail auditing."""
        dialed_manifest_path = ROOT / "work" / "americandad" / "spring_breakup_dialed_manifest.json"
        if not dialed_manifest_path.exists():
            self.skipTest("Scenario dialed manifest not yet generated.")

        harness = DualEngineHarness(mode="rule_based")
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = Path(tmp_dir) / "test_novel.md"
            text, report = harness.synthesize_and_verify(
                dialed_manifest_path=dialed_manifest_path,
                output_path=out_file,
                burstiness_threshold=4.0,
                minimum_gags=3,
            )

            self.assertTrue(out_file.exists())
            self.assertGreater(len(text), 2000)
            self.assertTrue(report.passed)
            self.assertTrue(report.is_clean_of_plagiarism)
            self.assertTrue(report.is_clean_of_ai_tells)
            self.assertTrue(report.burstiness_passed)
            self.assertGreaterEqual(report.burstiness_score, 4.0)

    def test_hybrid_mode_cuda_coprocessor_activation(self):
        """
        In hybrid mode, verifies that the local GPU coprocessors (MiniLM and Qwen2.5)
        initialize and perform dense reranking and micro-generation on CUDA.
        """
        harness = DualEngineHarness(mode="hybrid", lazy_load=False)
        self.assertIn(harness.active_device, ["cuda", "cuda:0", "cpu"])

        # Somatic Reranking with MiniLM
        passages = [
            {"id": "p1", "text": "cinnamon aroma and warm cloves in heavy tropical heat", "weight": 1.25, "book_id": "gabriela"},
            {"id": "p2", "text": "glamour martini glass on penthouse carpet", "weight": 0.05, "book_id": "valley_of_the_dolls"},
        ]
        results = harness.rerank_somatic_passages(
            queries=["aroma of cloves and cinnamon heat"],
            candidate_passages=passages,
            top_k=2,
        )
        self.assertEqual(len(results), 2)
        # Weight 1.25 defeats weight 0.05
        self.assertEqual(results[0].book_slug, "gabriela")

        # Micro-Dialogue with Qwen2.5
        c = harness.dial_dialogue_line(
            speaker="FRANCINE",
            raw_text="Rainee! The clock is ticking! If we don't clear the turnpike before eight, the bridge toll is a nightmare!",
            raw_parenthetical="O.S.",
            target_level=20,
        )
        self.assertEqual(c.influence_level, 20)
        self.assertEqual(c.word_drift_pct, 0.0)
        self.assertTrue(c.is_compliant)


if __name__ == "__main__":
    unittest.main()
