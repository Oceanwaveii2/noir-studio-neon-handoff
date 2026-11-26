"""Regression tests for the 2026-11-06 review findings (F1-F4)."""
import json, tempfile, unittest
from pathlib import Path
from prose_engine import guards
from prose_engine.providers.deepseek import BudgetExceeded, DeepSeekProvider
from prose_engine.voice.best_of_n import BestOfN
from prose_engine.voice.pipeline import Pipeline

REF = "Here she said, pulling out a five dollar bill here she said all alone she said sweetly to Helen."
COPY = "Francine stood there and a five dollar bill here she said and all alone she said sweetly to nobody."
CLEAN = "Francine stood at the counter and stirred her coffee four times."


class Ev:
    def similarity(self, t): return 0.6
    def percentile(self, t): return 0.5
    def record(self, d, l): pass


class Req:
    original_text = "Francine stands."


class Seq:
    model_name = "seq"
    def __init__(self, texts): self.texts = list(texts)
    def generate_rewrite(self, r, p): return self.texts.pop(0)


class Boom:
    model_name = "boom"
    def generate_rewrite(self, r, p): raise BudgetExceeded("cap")


class ReviewFixes(unittest.TestCase):
    def pipe(self, provider, n):
        return Pipeline(provider, Ev(), candidates=n, min_score=0.0, ledger=Path(tempfile.mkdtemp()) / "d.jsonl")

    def test_f1_reference_overlap_alone_keeps_candidate_eligible(self):
        result = self.pipe(Seq([COPY]), 1).rewrite("Francine stands.", "p", Req(), references=[REF])
        self.assertTrue(result.accepted, result.reason)
        self.assertEqual(result.text, COPY)

    def test_f1_reference_overlap_does_not_filter_the_ranked_pool(self):
        pipeline = self.pipe(Seq([COPY, CLEAN]), 2)
        pipeline.rewrite("Francine stands.", "p", Req(), references=[REF])
        self.assertCountEqual([candidate["text"] for candidate in pipeline.last_pool], [COPY, CLEAN])

    def test_f2_budget_error_surfaces(self):
        with self.assertRaises(BudgetExceeded):
            BestOfN(Ev()).run(Boom(), Req(), "p", n=3)

    def test_f3_curly_apostrophe_contraction_still_matches(self):
        ref = "I don\u2019t know how to thank you, Anne said quietly."
        cand = "I don't know how to thank you, Anne said quietly."
        self.assertTrue(guards.reference_copies(cand, [ref], 6))

    def test_f4_budget_persists_across_instances(self):
        ok = lambda p: {"usage": {"prompt_tokens": 1, "completion_tokens": 1}, "choices": [{"message": {"content": "x"}}]}
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "u.jsonl"
            DeepSeekProvider(api_key="k", max_calls=1, transport=ok, ledger=ledger).generate_rewrite(None, "p")
            second = DeepSeekProvider(api_key="k", max_calls=1, transport=ok, ledger=ledger)
            with self.assertRaises(BudgetExceeded):
                second.generate_rewrite(None, "p")


if __name__ == "__main__":
    unittest.main()
