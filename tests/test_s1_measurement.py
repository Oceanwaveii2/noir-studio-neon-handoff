"""S1 contracts: copy detector v2, diagnostics suite, typicality is a diagnostic."""

import unittest

from prose_engine.guards import copy_issues
from prose_engine.voice.diagnostics_suite import analyze

REFERENCE = (
    "She picked up her purse and rummaged in it, pulling out a five-dollar bill. "
    "Here, she said, you run the best john in town. She turned to Anne. Come on, let's leave "
    "the old bald eagle to cry in peace."
)

NAME_SWAPPED = (
    "She picked up her purse and rummaged in it, pulling out a five-dollar bill. "
    "Here, she said, you run the best john in town. She turned to Francine. Come on, let's leave "
    "the old bald eagle to cry in peace."
)

ORIGINAL = (
    "Francine dug through her bag until she found a crumpled bill, pressed it into the counter, "
    "and told the woman to keep the change. Then she took her daughter by the elbow and walked "
    "out into the parking lot without looking back."
)


class CopyGuardTests(unittest.TestCase):
    def test_name_swapped_copy_is_rejected(self):
        issues = copy_issues(NAME_SWAPPED, [REFERENCE])
        self.assertTrue(issues, "name-swapped copy must not pass")
        self.assertTrue(any("name-swapped" in issue or "verbatim" in issue for issue in issues))

    def test_original_paraphrase_passes(self):
        self.assertEqual(copy_issues(ORIGINAL, [REFERENCE]), [])

    def test_no_references_means_no_issues(self):
        self.assertEqual(copy_issues(ORIGINAL, []), [])


class DiagnosticSuiteTests(unittest.TestCase):
    def test_reports_named_metrics(self):
        result = analyze("She noticed the door. The air was thick with tension. Beat.")
        for key in ("tic", "filter", "simile", "participial", "cliche", "repetition"):
            self.assertIn(key, result["findings"])
        self.assertGreater(result["findings"]["filter"]["count"], 0)
        self.assertGreater(result["findings"]["cliche"]["count"], 0)

    def test_clean_prose_has_low_rates(self):
        result = analyze("Francine set the tray down. Rainee picked up the lipstick.")
        self.assertEqual(result["findings"]["filter"]["count"], 0)
        self.assertEqual(result["findings"]["simile"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
