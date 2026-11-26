"""S4: rule-based span flagger, no score, honest label status."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from prose_engine.voice.slop import flag


class FlaggerTests(unittest.TestCase):
    def rules(self, text):
        return {span.rule for span in flag(text)}

    def test_filter_rule(self):
        self.assertIn("filter", self.rules("She noticed the door and felt cold."))

    def test_beat_rule(self):
        self.assertIn("beat_cue", self.rules("Beat. She set the lipstick down."))

    def test_body_cliche_rule(self):
        self.assertIn("body_cliche", self.rules("Her heart pounded and her stomach dropped."))

    def test_author_avoid_rule(self):
        self.assertIn("author_avoid", self.rules("A low, distant gurgle answered, then a heat mirage."))

    def test_em_dash_gating(self):
        # single em-dash does not trigger (legitimate narrative pacing)
        self.assertNotIn("em_dash", self.rules("She stood \u2014 waiting by the door."))
        # density >= 2 triggers em-dash density flag
        self.assertIn("em_dash", self.rules("She stood \u2014 waiting by the door \u2014 before turning."))

    def test_clean_action_line_has_no_flags(self):
        self.assertEqual(flag("Francine set the tray down. Rainee picked up the lipstick."), [])

    def test_no_numeric_score_is_exposed(self):
        spans = flag("Beat. She noticed the door.")
        self.assertTrue(spans)
        self.assertFalse(any(hasattr(span, "score") for span in spans))


class LabelTests(unittest.TestCase):
    def test_labels_have_operation_and_doc(self):
        path = Path("books/corrections_v2.jsonl")
        self.assertTrue(path.is_file())
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()[:3]]
        for row in rows:
            self.assertIn("doc_id", row)
            self.assertIn(row["op"], {"delete", "keep", "note"})


class HonestEvalTests(unittest.TestCase):
    def test_eval_refuses_auc_on_small_fold(self):
        result = subprocess.run(
            [sys.executable, "tools/eval_slop.py"],
            capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1],
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("INSUFFICIENT LABELS", result.stdout)


if __name__ == "__main__":
    unittest.main()
