"""Variation engine contracts."""

import unittest

from prose_engine.voice.variations import VariationSet, prompt_for

FACTS = ["Rainee", "Peter Griffin", "lipstick"]
ORIGINAL = "Rainee farts, swells, and her face becomes Peter Griffin while the lipstick stays perfect."


class QueueProvider:
    model_name = "queue"

    def __init__(self, texts):
        self.texts = list(texts)

    def generate_rewrite(self, request, prompt):
        return self.texts.pop(0) if self.texts else ""


class VariationTests(unittest.TestCase):
    def test_prompt_carries_treatment_and_facts(self):
        prompt = prompt_for(FACTS, "curse", "card", ["liquid mercury"])
        self.assertIn("TREATMENT", prompt)
        self.assertIn("curse", prompt)
        self.assertIn("Rainee", prompt)
        self.assertIn("FORBIDDEN IMAGES", prompt)

    def test_tone_and_staging_rule(self):
        prompt = prompt_for(FACTS, "curse", tone="deadpan comedy", exemplars=["Still hot. Objectively."])
        self.assertIn("TONE: deadpan comedy", prompt)
        self.assertIn("STAGE, DO NOT ENUMERATE", prompt)
        self.assertIn("REGISTER EXAMPLES", prompt)

    def test_references_are_in_prompt(self):
        prompt = prompt_for(FACTS, "curse", references=["She walked in like a rumour."])
        self.assertIn("VOICE REFERENCES", prompt)
        self.assertIn("She walked in like a rumour.", prompt)

    def test_distinct_treatments_are_kept(self):
        provider = QueueProvider(
            [
                "Rainee lets out a curse-word of a fart. Peter Griffin's lipstick grin arrives with the swelling.",
                "A clinic machine misreads Rainee's chart. Her body swells; the lipstick stays. Peter Griffin looks back from the mirror.",
            ]
        )
        result = VariationSet(max_original_overlap=0.9).run(
            provider, type("R", (), {"original_text": ORIGINAL})(), ORIGINAL, FACTS,
            ["curse", "medical"],
        )
        self.assertEqual(len(result), 2)
        self.assertTrue(all(variant.accepted for variant in result), [v.reason for v in result])

    def test_duplicate_treatment_is_rejected(self):
        text = "Rainee farts and swells into Peter Griffin while the lipstick stays perfect."
        provider = QueueProvider([text, text])
        result = VariationSet(max_original_overlap=0.9).run(
            provider, type("R", (), {"original_text": ORIGINAL})(), ORIGINAL, FACTS,
            ["curse", "curse"],
        )
        self.assertTrue(result[0].accepted)
        self.assertFalse(result[1].accepted)
        self.assertIn("too similar", result[1].reason)

    def test_missing_fact_is_rejected(self):
        provider = QueueProvider(["Rainee farts and swells into a cartoon shape."])
        result = VariationSet(max_original_overlap=0.9).run(
            provider, type("R", (), {"original_text": ORIGINAL})(), ORIGINAL, FACTS,
            ["curse"],
        )
        self.assertFalse(result[0].accepted)
        self.assertIn("drops facts", result[0].reason)


if __name__ == "__main__":
    unittest.main()
