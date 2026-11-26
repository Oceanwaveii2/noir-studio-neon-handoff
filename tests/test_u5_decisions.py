import unittest
from tools.eval_decisions import summarize


class AuthorEvaluationTests(unittest.TestCase):
    def test_legacy_and_gate_passes_do_not_count_as_author_acceptance(self):
        report = summarize([
            {"accepted": True, "provider": "local-edits"},
            {"record_type": "author_decision", "reviewer": " ", "decision": "accept"},
            {"record_type": "gate_result", "result": "pass"},
        ], [{"accepted": True}])
        self.assertEqual(report["author"]["status"], "pending")
        self.assertIsNone(report["author"]["accept_rate"])
        self.assertIsNone(report["author"]["accept_rate_wilson_95"])
        self.assertEqual(report["automatic_gate"]["total"], 1)
        self.assertEqual(report["unclassified_decision_rows"], 2)

    def test_named_outcomes_keep_independent_denominators(self):
        decisions = [{"record_type": "author_decision", "reviewer": "Reviewer",
                      "decision": value}
                     for value in ("accept", "keep_original", "tie", "reject")]
        decisions.append({"record_type": "gate_result", "result": "fail"})
        report = summarize(decisions, [])
        self.assertEqual(report["author"]["counts"],
                         {"accept": 1, "keep_original": 1, "reject": 1, "tie": 1})
        self.assertEqual(report["author"]["total"], 4)
        self.assertEqual(report["author"]["accept_rate"], .25)
        lo, hi = report["author"]["accept_rate_wilson_95"]
        self.assertLess(lo, .25)
        self.assertGreater(hi, .25)
        self.assertEqual(report["automatic_gate"]["total"], 1)
