"""Offline Prose Quality Benchmark & Regression Suite (Milestone 2.5).

Proves measurable improvement of NOIR 5-Pass outputs over raw sloppy LLM prose
across 5 deterministic axes:
  1. Composite Slop Score (binary contrasts, false agency, vocab-maxxing, n-grams)
  2. Sentence-length burstiness (sigma >= 4.0)
  3. Speaker dialogue voice divergence & 0% LOCK asymmetric relationship cues
  4. Diversified stylized SFX with zero back-to-back duplicates
  5. Compact positive rhythm skeleton within token budget + 190-book catalog
"""

from __future__ import annotations

import unittest

from prose_engine.conditioner import build_rhythm_skeleton, surgical_pass5_rewrite
from prose_engine.dialogue_dial import (
    condition_dialogue_from_relationship,
    score_speaker_divergence,
)
from prose_engine.linter import AntiAILinter, LinterReport, compute_composite_slop_score
from prose_engine.sfx_stylizer import SfxStylizer, generate_scene_sfx


RAW_SLOPPY_LLM_TEXT = (
    "Because of this, Francine gripped the porcelain counter with white-knuckles. "
    "It wasn't fear—it was a quiet devastation. "
    "She felt the silence demanded an answer, leaving her no room to breathe. "
    "Not a victory, but a trap. "
    "The hallway unfolded like a tapestry of pale blush and palpable tension. "
    "She couldn't help but feel the cold handle. "
    "She gripped the counter. She gripped the counter. She gripped the counter."
)

CLEAN_CRAFT_TEXT = (
    "Francine dropped the ceramic casserole onto the granite. "
    "A hairline crack split the glaze near the handle, leaking lukewarm gravy across the grocery receipt. "
    "Rainee froze by the bathroom door.\n\n"
    "Downstairs, the radiator knocked twice against the baseboard before settling into a wet hiss. "
    "Nobody spoke. "
    "Francine checked her wristwatch, wiped her knuckles on a dish towel, and reached for the car keys."
)


class ProseQualityBenchmarkTests(unittest.TestCase):
    def test_composite_slop_score_separates_slop_from_craft(self) -> None:
        slop = compute_composite_slop_score(RAW_SLOPPY_LLM_TEXT)
        craft = compute_composite_slop_score(CLEAN_CRAFT_TEXT)

        self.assertGreaterEqual(slop["score"], 40.0)
        self.assertLessEqual(craft["score"], 15.0)
        self.assertGreaterEqual(craft["burstiness"], 4.0)
        self.assertTrue(craft["burstiness_passed"])
        self.assertGreaterEqual(slop["by_category"]["binary_contrast"], 2)
        self.assertGreaterEqual(slop["by_category"]["false_agency"], 1)
        self.assertGreaterEqual(slop["by_category"]["vocab_maxxing"], 1)
        self.assertTrue(len(slop["repeated_ngrams"]) >= 1)

    def test_surgical_pass5_rewrite_reduces_slop_and_preserves_frozen_dialogue(self) -> None:
        frozen_1 = 'FRANCINE\n"Rainee, let\'s go! Okay, Rainee, let\'s get going!"'
        frozen_2 = 'RAINEE\n"Absolutely not."'
        hybrid_text = (
            f"{frozen_1}\n\n"
            "Because of this, Rainee stood with white-knuckles by the sink, leaving her no way out. "
            "It wasn't panic—it was a tapestry of palpable tension. "
            "She couldn't help but watch as the silence demanded obedience.\n\n"
            f"{frozen_2}"
        )

        result = surgical_pass5_rewrite(hybrid_text, frozen_spans=[frozen_1, frozen_2])
        self.assertTrue(result["locked_bytes_intact"])
        self.assertIn(frozen_1, result["text"])
        self.assertIn(frozen_2, result["text"])
        self.assertLess(result["slop_after"], result["slop_before"] - 15.0)

    def test_speaker_voice_divergence_and_asymmetric_relationship(self) -> None:
        distinct_lines = [
            {"speaker": "FRANCINE", "text": "Move. Keys are on the counter. Turnpike closes at eight."},
            {"speaker": "FRANCINE", "text": "Three nights of lasagna. Do not touch the mystery casserole."},
            {
                "speaker": "RAINEE",
                "text": "Wait—no, Francine, my hair isn't even dry yet and you want me to ride five hours in a wool sweater?!",
            },
            {
                "speaker": "ROGER",
                "text": "Darling, if we are embarking upon an odyssey of domestic martyrdom, I insist on bringing my velvet shawl and three vintage decanters.",
            },
        ]
        div_distinct = score_speaker_divergence(distinct_lines)
        self.assertTrue(div_distinct["passed"])
        self.assertGreaterEqual(div_distinct["divergence_score"], 35.0)

        flat_lines = [
            {"speaker": "CHAR_A", "text": "We must understand the situation before we leave the house."},
            {"speaker": "CHAR_B", "text": "We must understand the situation before we leave the house."},
        ]
        div_flat = score_speaker_divergence(flat_lines)
        self.assertLess(div_flat["divergence_score"], div_distinct["divergence_score"])

        raw_line = "Rainee, let's go!"
        conditioned = condition_dialogue_from_relationship(
            speaker="FRANCINE",
            line=raw_line,
            relationship_edge={
                "direction": "FRANCINE->RAINEE",
                "patience": 0.15,
                "friction": 0.80,
                "bridging_direction": "shouting up the stairwell",
            },
            influence_level=0,
        )
        self.assertTrue(conditioned["locked"])
        self.assertEqual(conditioned["word_drift_pct"], 0.0)
        self.assertEqual(conditioned["spoken_text"], raw_line)
        self.assertIn("short clipped impatience", conditioned["stage_direction"])

    def test_sfx_stylizer_zero_back_to_back_duplicates_and_tone_adaptation(self) -> None:
        events = [{"category": "impact", "tone": "dry_comedy", "intensity": 0.6} for _ in range(10)]
        batch = generate_scene_sfx(events, decay_window=6)
        self.assertEqual(batch["metrics"]["back_to_back_duplicates"], 0)
        self.assertGreaterEqual(batch["metrics"]["unique_ratio"], 0.8)

        comedy_sfx = SfxStylizer().stylize("door_slam", tone="dry_comedy")["sfx"]
        noir_sfx = SfxStylizer().stylize("door_slam", tone="noir")["sfx"]
        self.assertNotEqual(comedy_sfx, noir_sfx)

    def test_rhythm_skeleton_respects_token_budget_and_reports_library(self) -> None:
        skel = build_rhythm_skeleton(token_budget=130, books_dir="books")
        self.assertTrue(skel["within_budget"])
        self.assertLessEqual(skel["approx_tokens"], 130)
        self.assertGreaterEqual(skel["library_books_indexed"], 138)

    def test_existing_linter_backward_compatible(self) -> None:
        report = AntiAILinter().lint(CLEAN_CRAFT_TEXT)
        self.assertIsInstance(report, LinterReport)
        self.assertTrue(hasattr(report, "total_violations"))
        self.assertTrue(hasattr(report, "burstiness_score"))
        self.assertTrue(hasattr(report, "burstiness_passed"))
        self.assertTrue(hasattr(report, "passed"))
        self.assertTrue(hasattr(report, "summary"))
        self.assertTrue(report.passed)


if __name__ == "__main__":
    unittest.main()
