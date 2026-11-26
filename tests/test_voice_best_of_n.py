"""Best-of-N and logit-rule contracts."""

import unittest

try:
    import torch
except Exception:  # optional dependency in clean checkouts
    torch = None

from prose_engine.voice.best_of_n import BestOfN, Candidate, score_text, select, select_all
from prose_engine.voice.logit_rules import BannedPhraseProcessor


class FakeEvaluator:
    def __init__(self, scores):
        self.scores = scores

    def similarity(self, text):
        return self.scores.get(text, 0.0)


class FakeProvider:
    model_name = "fake"

    def __init__(self, texts):
        self.texts = list(texts)

    def generate_rewrite(self, request, prompt):
        return self.texts.pop(0)


class BestOfNTests(unittest.TestCase):
    def test_similarity_is_not_the_selector(self):
        low = score_text("a b c", similarity=0.2, style=1.0, overlap=0.5)
        high = score_text("a b c", similarity=0.6, style=1.0, overlap=0.5)
        self.assertEqual(high.score, low.score)
        self.assertNotEqual(high.parts["similarity"], low.parts["similarity"])

    def test_more_tics_scores_lower(self):
        clean = score_text("She walks to the door and opens it.", similarity=0.5, style=1.0, overlap=0.4)
        tic = score_text(
            "She walks to the door, smiling, breathing, remembering, and feeling the weight of it all.",
            similarity=0.5, style=1.0, overlap=0.4,
        )
        self.assertGreater(clean.score, tic.score)

    def test_select_accepts_close_call_above_floor(self):
        close = [Candidate("a", score=0.50), Candidate("b", score=0.49)]
        self.assertEqual(select(close, margin=0.03, min_score=0.45).text, "a")
        clear = [Candidate("a", score=0.60), Candidate("b", score=0.40)]
        self.assertEqual(select(clear, margin=0.03, min_score=0.45).text, "a")

    def test_voice_signal_is_diagnostic_only(self):
        low = score_text("a b c", similarity=0.5, style=1.0, overlap=0.3, voice=0.25)
        high = score_text("a b c", similarity=0.5, style=1.0, overlap=0.3, voice=0.75)
        self.assertEqual(high.score, low.score)
        self.assertGreater(high.parts["voice"], low.parts["voice"])

    def test_select_records_margin(self):
        close = [Candidate("a", score=0.50), Candidate("b", score=0.49)]
        self.assertEqual(select(close, margin=0.03).parts.get("margin_ok"), 0.0)
        clear = [Candidate("a", score=0.60), Candidate("b", score=0.40)]
        self.assertEqual(select(clear, margin=0.03).parts.get("margin_ok"), 1.0)

    def test_select_tie_breaks_on_lower_overlap(self):
        cand1 = Candidate("a long sentence", score=0.50, parts={"overlap": 0.5})
        cand2 = Candidate("short", score=0.49, parts={"overlap": 0.9})
        winner = select([cand1, cand2], margin=0.03, min_score=0.45)
        self.assertEqual(winner.text, "short")
        self.assertEqual(winner.parts.get("tie"), 1.0)

    def test_luar_scorer_uses_best_cosine(self):
        import numpy as np
        from prose_engine.voice.luar import LuarScorer

        class FakeEncoder:
            def encode(self, texts):
                return np.array([[1.0, 0.0]])

        class FakeIndex:
            vectors = np.array([[1.0, 0.0], [0.0, 1.0]])

        self.assertAlmostEqual(LuarScorer(FakeIndex(), FakeEncoder()).score("x"), 1.0, places=4)

    def test_close_call_returns_two_candidates(self):
        close = [Candidate("a", score=0.50), Candidate("b", score=0.49)]
        self.assertEqual(len(select_all(close, margin=0.03, min_score=0.0)), 2)
        clear = [Candidate("a", score=0.60), Candidate("b", score=0.40)]
        self.assertEqual(len(select_all(clear, margin=0.03, min_score=0.0)), 1)

    def test_select_rejects_below_min_score(self):
        weak = [Candidate("a", score=0.2), Candidate("b", score=0.1)]
        self.assertIsNone(select(weak, margin=0.03, min_score=0.45))

    def test_best_of_n_runs_all_candidates(self):
        provider = FakeProvider(["A door opens.", "A door opens slowly.", "Nothing."])
        evaluator = FakeEvaluator({"A door opens.": 0.3, "A door opens slowly.": 0.7, "Nothing.": 0.1})
        request = type("Request", (), {"original_text": "The door opened."})()
        candidates = BestOfN(evaluator, style_model=None).run(provider, request, "prompt", n=3)
        self.assertEqual(len(candidates), 3)
        # S2: selection is gate-first with a brevity bias; "Nothing." is the shortest clean candidate
        self.assertEqual(max(candidates, key=lambda c: c.score).text, "Nothing.")


class CopyGuardTests(unittest.TestCase):
    def test_shared_six_gram_is_caught(self):
        from prose_engine.guards import reference_copies

        reference = "the room was less a bedroom than a dressing room that happens to contain a bed"
        candidate = "She paused. the room was less a bedroom than a dressing room and she hated it."
        self.assertTrue(reference_copies(candidate, [reference], 6))

    def test_paraphrase_is_not_caught(self):
        from prose_engine.guards import reference_copies

        reference = "the room was less a bedroom than a dressing room that happens to contain a bed"
        candidate = "The bedroom doubled as a dressing room; the bed was almost an afterthought."
        self.assertEqual(reference_copies(candidate, [reference], 6), [])


class PersonificationTests(unittest.TestCase):
    def test_object_cannot_laugh(self):
        from prose_engine.guards import personification_issues

        self.assertTrue(personification_issues('Tupperware laughed. "Send me the bill," it said.'))

    def test_a_person_can_laugh(self):
        from prose_engine.guards import personification_issues

        self.assertEqual(personification_issues("Francine laughed and set the tray down."), [])


class ReferenceBlockTests(unittest.TestCase):
    def test_block_carries_books(self):
        from prose_engine.voice.references import format_references

        block = format_references(["She walked in like a rumour."])
        self.assertIn("VOICE REFERENCES", block)
        self.assertIn("rumour", block)

    def test_empty_block_is_empty(self):
        from prose_engine.voice.references import format_references

        self.assertEqual(format_references([]), "")


class FakeTokenizer:
    def encode(self, text, add_special_tokens=False):
        return {
            "like": [10],
            " like": [11],
            "as if": [12, 13],
            " as if": [14, 15],
        }[text]


@unittest.skipUnless(torch is not None, "torch not installed (optional local extra)")
class LogitRuleTests(unittest.TestCase):
    def test_single_token_phrase_is_banned(self):
        processor = BannedPhraseProcessor(FakeTokenizer(), ["like"])
        scores = torch.zeros(1, 20)
        processor(torch.tensor([[5, 6]]), scores)
        self.assertEqual(scores[0, 10].item(), float("-inf"))
        self.assertEqual(scores[0, 11].item(), float("-inf"))

    def test_multi_token_prefix_bans_next_token(self):
        processor = BannedPhraseProcessor(FakeTokenizer(), ["as if"])
        scores = torch.zeros(1, 20)
        processor(torch.tensor([[5, 14]]), scores)
        self.assertEqual(scores[0, 15].item(), float("-inf"))
        self.assertEqual(scores[0, 16].item(), 0.0)

    def test_prompt_tokens_are_not_banned(self):
        processor = BannedPhraseProcessor(FakeTokenizer(), ["like"], prompt_length=2)
        scores = torch.zeros(1, 20)
        processor(torch.tensor([[5, 6]]), scores)
        self.assertEqual(scores[0, 10].item(), 0.0)


if __name__ == "__main__":
    unittest.main()
