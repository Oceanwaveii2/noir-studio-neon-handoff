"""Critique and pipeline contracts."""

import tempfile
import unittest
from pathlib import Path

from prose_engine.voice.bible import Bible, Character
from prose_engine.voice.critique import Issue, collect, prompt_for
from prose_engine.voice.pipeline import Pipeline

ORIGINAL = "The sedan sits at the curb and Rainee walks to the porch where Ma Ma Ling waits."


class FakeEvaluator:
    def __init__(self, scores):
        self.scores = scores
        self.recorded = []

    def similarity(self, text):
        return self.scores.get(text, 0.2)

    def percentile(self, text):
        return 0.5

    def record(self, decision, ledger):
        self.recorded.append(decision)
        return Path(ledger)


class FakeProvider:
    model_name = "fake"

    def __init__(self, texts):
        self.texts = list(texts)

    def generate_rewrite(self, request, prompt):
        return self.texts.pop(0) if self.texts else request.original_text


class CritiqueTests(unittest.TestCase):
    def test_forbidden_claim_becomes_issue(self):
        bible = Bible(characters={"haley": Character(forbidden_claims=["hair vanished"])})
        issues = collect("Haley's hair vanished.", bible=bible)
        self.assertTrue(any(issue.rule == "forbidden_claim" for issue in issues))

    def test_tic_becomes_issue(self):
        issues = collect("She crosses the room, smiling. He waits, breathing. The lamp hums, flickering.")
        self.assertTrue(any(issue.rule == "participial_tail" for issue in issues))

    def test_prompt_lists_issues(self):
        text = prompt_for([Issue("forbidden_claim", "haley: hair vanished")], "Some paragraph.")
        self.assertIn("FIX ONLY THESE ISSUES", text)
        self.assertIn("hair vanished", text)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = str(Path(self.tmp.name) / "decisions.jsonl")
        self.evaluator = FakeEvaluator(
            {
                "Rainee reaches the porch. The sedan waits at the curb, and Ma Ma Ling stands there.": 0.9,
                "A woman walks to a house.": 0.3,
                "A woman reaches the porch. The sedan waits.": 0.8,
                "Rainee reaches the porch. Ma Ma Ling stands there with her arms folded.": 0.8,
            }
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_accepts_the_best_clear_candidate(self):
        provider = FakeProvider(
            [
                "Rainee reaches the porch. The sedan waits at the curb, and Ma Ma Ling stands there.",
                "A woman walks to a house.",
            ]
        )
        request = type("Request", (), {"original_text": ORIGINAL})()
        pipeline = Pipeline(provider, self.evaluator, candidates=2, ledger=self.ledger)
        result = pipeline.rewrite(ORIGINAL, "prompt", request, scene="porch", max_overlap=0.9)
        self.assertTrue(result.accepted, result.reason)
        self.assertIn("Ma Ma Ling", result.text)
        self.assertEqual(len(self.evaluator.recorded), 1)

    def test_rejects_candidate_that_drops_a_name(self):
        provider = FakeProvider(["A woman reaches the porch. The sedan waits."])
        request = type("Request", (), {"original_text": ORIGINAL})()
        pipeline = Pipeline(provider, self.evaluator, candidates=1, ledger=self.ledger)
        result = pipeline.rewrite(ORIGINAL, "prompt", request, scene="porch", max_overlap=0.9)
        self.assertFalse(result.accepted)
        self.assertIn("drops facts", result.reason)

    def test_rejects_contract_violation(self):
        from prose_engine.voice.scene import Contract

        contract = Contract(scene_id="porch", facts=["the sedan is at the curb"])
        provider = FakeProvider(
            ["Rainee reaches the porch. Ma Ma Ling stands there with her arms folded."]
        )
        request = type("Request", (), {"original_text": ORIGINAL})()
        pipeline = Pipeline(provider, self.evaluator, candidates=1, ledger=self.ledger)
        result = pipeline.rewrite(ORIGINAL, "prompt", request, contract=contract, scene="porch", max_overlap=0.9)
        self.assertFalse(result.accepted)
        self.assertIn("unresolved", result.reason)


if __name__ == "__main__":
    unittest.main()
