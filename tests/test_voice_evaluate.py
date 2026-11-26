"""Evaluation and tic contracts."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from prose_engine.voice.evaluate import Decision, Evaluator, report
from prose_engine.voice.tics import counts, scan


class EvaluatorTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        corpus = rng.normal(size=(50, 8)).astype("float32")
        self.evaluator = Evaluator(vectors=corpus, encode=lambda text: corpus[0])

    def test_similarity_is_bounded(self):
        value = self.evaluator.similarity("any text")
        self.assertGreaterEqual(value, -1.0)
        self.assertLessEqual(value, 1.0)

    def test_percentile_between_zero_and_one(self):
        value = self.evaluator.percentile("any text")
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)

    def test_decision_round_trip_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "decisions.jsonl"
            self.evaluator.record(
                Decision(scene="s", paragraph=1, accepted=True, similarity=0.5, percentile=0.2),
                ledger,
            )
            self.evaluator.record(
                Decision(scene="s", paragraph=2, accepted=False, similarity=0.3, percentile=0.1),
                ledger,
            )
            result = report(ledger)
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["accepted"], 1)
            self.assertEqual(result["accept_rate"], 0.5)
            self.assertEqual(result["mean_similarity_accepted"], 0.5)
            self.assertEqual(result["mean_percentile_accepted"], 0.2)

    def test_report_zero_accepted_yields_none_mean_similarity(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "decisions.jsonl"
            self.evaluator.record(
                Decision(scene="s", paragraph=1, accepted=False, similarity=0.7),
                ledger,
            )
            result = report(ledger)
            self.assertIsNone(result["mean_similarity_accepted"])
            self.assertIsNone(result["mean_percentile_accepted"])


class TicTests(unittest.TestCase):
    def test_participial_tails_flagged(self):
        text = (
            "She crosses the room, smiling. He waits by the door, breathing hard. "
            "The lamp hums, flickering."
        )
        self.assertIn("participial_tail", counts(text))

    def test_clean_prose_has_no_participial_warning(self):
        text = "She crosses the room. He waits by the door. The lamp hums."
        self.assertNotIn("participial_tail", counts(text))

    def test_excess_lexicon_needs_two_distinct_words(self):
        one = "She delved into the box."
        two = "She delved into the intricate box."
        self.assertNotIn("excess_lexicon", counts(one))
        self.assertIn("excess_lexicon", counts(two))

    def test_negative_parallelism(self):
        self.assertIn(
            "negative_parallelism",
            counts("It was not just a car but a statement about who he was."),
        )

    def test_beat_direction(self):
        self.assertIn("beat_direction", counts("Beat.\nShe sets the lipstick down."))

    def test_findings_have_spans(self):
        text = "Beat.\nShe sets the lipstick down."
        for finding in scan(text):
            self.assertLessEqual(finding.start, finding.end)
            self.assertTrue(finding.advice)

    def test_blacklisted_musical_flatulence(self):
        from prose_engine.voice.tics import blacklisted_cliches
        bad = "Then a monumental baritone trombone glissando shakes the room."
        self.assertIn("baritone trombone", blacklisted_cliches(bad))
        self.assertIn("glissando", blacklisted_cliches(bad))

    def test_blacklisted_beverage_straw(self):
        from prose_engine.voice.tics import blacklisted_cliches
        bad = "She listened to the slurping death-rattle of her straw."
        self.assertIn("slurping death-rattle", blacklisted_cliches(bad))

    def test_blacklisted_pseudo_mechanical(self):
        from prose_engine.voice.tics import blacklisted_cliches
        bad = "Pneumatic hydraulic force explodes into her lower half with displacement of mass."
        cliches = blacklisted_cliches(bad)
        self.assertIn("pneumatic", cliches)
        self.assertIn("hydraulic", cliches)
        self.assertIn("displacement of mass", cliches)

    def test_blacklisted_military_hyperbole(self):
        from prose_engine.voice.tics import blacklisted_cliches
        bad = "The laugh is a fatal tactical error that shatters her seal."
        cliches = blacklisted_cliches(bad)
        self.assertIn("fatal tactical error", cliches)
        self.assertIn("shatters her seal", cliches)

    def test_clean_prose_has_no_blacklisted_cliches(self):
        from prose_engine.voice.tics import blacklisted_cliches
        clean = "Rainee winces. Francine laughs and pours another cup of hot black coffee."
        self.assertEqual(blacklisted_cliches(clean), [])


if __name__ == "__main__":
    unittest.main()
