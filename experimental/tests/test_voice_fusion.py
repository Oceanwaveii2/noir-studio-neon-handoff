"""Fusion and tell-gate contracts."""

import unittest

from prose_engine.voice.fusion import Fusion, fusion_prompt, rubric_block
from prose_engine.voice.tellgate import build_profile, score


class QueueProvider:
    model_name = "queue"

    def __init__(self, texts):
        self.texts = list(texts)

    def generate_rewrite(self, request, prompt):
        return self.texts.pop(0) if self.texts else ""


FACTS = "Rainee walks to the porch where Ma Ma Ling waits."


class FusionTests(unittest.TestCase):
    def test_rubric_has_five_items(self):
        self.assertEqual(rubric_block().count("\n"), 5)
        self.assertIn("comparisons", rubric_block())

    def test_prompt_contains_drafts(self):
        prompt = fusion_prompt(FACTS, ["draft one", "draft two", "draft three"])
        self.assertIn("DRAFT 1", prompt)
        self.assertIn("draft three", prompt)

    def test_fusion_accepts_a_faithful_synthesis(self):
        provider = QueueProvider(
            [
                "Rainee reaches the porch.",
                "Ma Ma Ling waits on the porch.",
                "Rainee crosses to the porch where Ma Ma Ling is waiting.",
                "Rainee crosses the walk to the porch. Ma Ma Ling waits there, arms folded, saying nothing.",
            ]
        )
        result = Fusion(provider, drafts=3).run(FACTS, "prompt", type("R", (), {"original_text": FACTS})(), max_overlap=0.9)
        self.assertTrue(result.accepted, result.reason)
        self.assertIn("Ma Ma Ling", result.text)
        self.assertEqual(len(result.drafts), 3)

    def test_fusion_rejects_synthesis_that_drops_a_name(self):
        provider = QueueProvider(
            ["Rainee waits.", "A woman waits.", "Someone waits.", "A woman stands on a porch and says nothing at all."]
        )
        result = Fusion(provider, drafts=3).run(FACTS, "prompt", type("R", (), {"original_text": FACTS})(), max_overlap=0.9)
        self.assertFalse(result.accepted)
        self.assertIn("drops facts", result.reason)

    def test_falls_back_to_longest_draft(self):
        provider = QueueProvider(["Rainee waits.", "Rainee waits for Ma Ma Ling on the porch.", "Rainee waits."])
        result = Fusion(provider, drafts=3).run(FACTS, "prompt", type("R", (), {"original_text": FACTS})(), max_overlap=0.9)
        self.assertTrue(result.text)
        self.assertIn("synthesis failed", result.reason)


class TellGateTests(unittest.TestCase):
    def test_profile_finds_overrepresented_trigram(self):
        generated = ["was the room"] * 10
        reference = ["the room was warm and bright"] * 60
        profile = build_profile(generated, reference, min_ratio=2, min_count=2, min_df=3)
        phrases = [phrase for phrase, _ in profile["banlist"]]
        self.assertTrue(any("was the room" in phrase for phrase in phrases), phrases[:5])

    def test_score_flags_banlisted_phrase(self):
        profile = {"banlist": [("the air was", 10.0)]}
        report = score("The air was thick with smoke.", profile)
        self.assertIn("the air was", report.hits)
        self.assertGreater(report.density, 0)

    def test_clean_text_passes(self):
        profile = {"banlist": [("the air was", 10.0)]}
        report = score("She opens the door and steps into the rain.", profile)
        self.assertEqual(report.hits, [])


if __name__ == "__main__":
    unittest.main()
