"""Fixture tests: expected values come from the contract, not from the implementation's output."""

import json
import unittest
from pathlib import Path

from prose_engine.guards import missing_facts, token_overlap

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "guards.json").read_text(encoding="utf-8")
)


class GuardContractTests(unittest.TestCase):
    def test_dropped_name_is_reported(self):
        case = FIXTURES["fact_case"]
        missing = missing_facts(case["original"], case["candidate"])
        for expected in case["expect_missing"]:
            self.assertIn(expected, missing)

    def test_exact_copy_has_full_overlap(self):
        case = FIXTURES["copy_case"]
        self.assertAlmostEqual(
            token_overlap(case["original"], case["candidate"]), case["expect_overlap"], places=3
        )

    def test_unbalanced_quotes_are_odd(self):
        case = FIXTURES["quote_case"]
        text = case["candidate"]
        quotes = text.count('"') + text.count("\u201c") + text.count("\u201d")
        self.assertEqual(quotes % 2 == 1, case["expect_odd"])

    def test_terse_candidate_falls_below_length_floor(self):
        case = FIXTURES["length_case"]
        ratio = len(case["candidate"]) / len(case["original"])
        self.assertLess(ratio, case["expect_ratio_below"])


if __name__ == "__main__":
    unittest.main()
