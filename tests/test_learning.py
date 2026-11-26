"""Contrastive exemplars and preference calibration contracts."""

import json
import tempfile
import unittest
from pathlib import Path

from prose_engine import exemplars
from prose_engine.preferences import load_proposals, suggest, summarize


class ExemplarTests(unittest.TestCase):
    def test_simile_warning_selects_simile_negative(self):
        chosen = exemplars.select(["Simile pileup (3 comparisons in 117 words)."])
        self.assertTrue(chosen)
        self.assertEqual(chosen[0]["tic"], "simile pileup")

    def test_filter_warning_selects_filter_negative(self):
        chosen = exemplars.select(["Filter words detected (2): saw, felt."])
        self.assertTrue(any(item["tic"] == "filter words" for item in chosen))

    def test_block_names_the_failure_modes(self):
        block = exemplars.block(exemplars.select(["Simile pileup."]))
        self.assertIn("DO NOT IMITATE", block)
        self.assertIn("why:", block)

    def test_no_warnings_means_no_block(self):
        self.assertEqual(exemplars.block(exemplars.select([])), "")


class PreferenceTests(unittest.TestCase):
    def test_summary_and_suggestion(self):
        rows = [
            {"accepted": True, "reason": "ok", "overlap": 0.30, "ratio": 0.9},
            {"accepted": True, "reason": "ok", "overlap": 0.40, "ratio": 1.1},
            {"accepted": False, "reason": "too close to the original", "overlap": 0.80, "ratio": 1.0},
        ]
        summary = summarize(rows)
        self.assertEqual(summary["accepted"], 2)
        self.assertEqual(summary["accepted_overlap_max"], 0.4)
        self.assertEqual(
            summary["rejection_reasons"]["too close to the original"], 1
        )
        suggestion = suggest(summary)
        self.assertGreaterEqual(suggestion["max_overlap"], 0.4)
        self.assertLessEqual(suggestion["max_overlap"], 0.9)

    def test_load_proposals_reads_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposals.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "accepted": True,
                            "reason": "ok",
                            "original": "The cat sat on the mat and looked at the door.",
                            "proposed": "A cat took the mat by force and dared the door to open.",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            rows = load_proposals([str(Path(tmp) / "*.json")])
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["accepted"])


if __name__ == "__main__":
    unittest.main()
