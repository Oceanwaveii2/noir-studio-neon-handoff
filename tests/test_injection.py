"""Tests for Milestone M11: Active Stylistic Injection Engine."""

import unittest
from pathlib import Path

from prose_engine.voice.injection import (
    load_all_banks,
    get_lens_bank,
    sample_idioms,
    sample_rhythm,
    format_injection_prompt,
    calculate_borrow_rate,
)
from prose_engine.prompt_assembler import PromptAssembler
from prose_engine.models import ProseRewriteRequest, ProseDiagnosticReport, SpanCategory
from prose_engine.style_engine import STANDARD_DRAMATIC


class InjectionTests(unittest.TestCase):
    def test_load_all_banks(self):
        banks = load_all_banks()
        self.assertIn("lenses", banks)
        for lens_id in ["irby", "tarantino", "glamour", "pop", "lockwood"]:
            self.assertIn(lens_id, banks["lenses"])
            bank = banks["lenses"][lens_id]
            self.assertTrue(len(bank.get("idioms", [])) >= 15)
            self.assertTrue(len(bank.get("rhythmic_patterns", [])) >= 2)

    def test_sample_idioms_and_rhythm(self):
        idioms = sample_idioms("tarantino", count=3, seed=42)
        self.assertEqual(len(idioms), 3)
        for idiom in idioms:
            self.assertIsInstance(idiom, str)
            self.assertTrue(len(idiom) > 5)

        rhythm = sample_rhythm("pop", seed=42)
        self.assertIsInstance(rhythm, str)
        self.assertTrue(len(rhythm) > 10)

    def test_format_injection_prompt(self):
        prompt = format_injection_prompt("glamour", count=3, seed=10)
        self.assertIn("ACTIVE STYLISTIC INJECTION", prompt)
        self.assertIn("JACKIE COLLINS", prompt)
        self.assertIn("STYLE MANDATE", prompt)
        self.assertIn("SIGNATURE IDIOMS", prompt)
        self.assertIn("DIRECTIVE", prompt)

    def test_calculate_borrow_rate(self):
        # Text containing Samantha Irby collocations
        irby_text = (
            "My stomach staging a full-scale riot while I was sweating down the side of my neck. "
            "I ended up dragging myself across the carpet in an ungainly penguin waddle."
        )
        rate = calculate_borrow_rate(irby_text, "irby")
        self.assertGreater(rate, 0.05)

        # Text with no Irby collocations
        clean_text = "The quick brown fox jumps over the lazy dog."
        self.assertEqual(calculate_borrow_rate(clean_text, "irby"), 0.0)

    def test_prompt_assembler_with_lens(self):
        req = ProseRewriteRequest(
            request_id="test-1",
            project_id="test",
            document_id="doc-1",
            base_revision=1,
            target_span_id="s1",
            original_text="Rainee looked at the counter.",
            category=SpanCategory.GENERAL,
        )
        diag = ProseDiagnosticReport(
            request_id="test-1",
            span_id="s1",
            filter_word_count=0,
            filter_words_found=[],
            label_syntax_detected=False,
            label_examples=[],
            sensory_details_count=1,
            sensory_preferences_detected=["smell"],
            burstiness_score=3.5,
            length_variance=2.0,
            sentence_count=1,
        )
        assembled = PromptAssembler.assemble(
            request=req,
            diagnostics=diag,
            style_profile=STANDARD_DRAMATIC,
            approved_edits=[],
            reference_passages=[],
            lens_id="tarantino",
        )
        self.assertIn("ACTIVE STYLISTIC INJECTION (QUENTIN TARANTINO)", assembled)
        self.assertIn("SIGNATURE IDIOMS", assembled)


if __name__ == "__main__":
    unittest.main()
