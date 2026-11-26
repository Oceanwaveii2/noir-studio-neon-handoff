"""S0: present-tense action lines must be flagged (regression fixture)."""

import json
import unittest
from pathlib import Path

from prose_engine.diagnostics import ProseDiagnosticsAnalyzer

FIXTURE = Path("tests/fixtures/present_tense.json")


class PresentTenseTests(unittest.TestCase):
    def test_every_present_tense_line_is_flagged(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        misses = []
        for line in data["lines"]:
            report = ProseDiagnosticsAnalyzer.analyze(line)
            flagged = (
                report.warnings
                or report.filter_word_count
                or report.label_examples
            )
            if not flagged:
                misses.append(line)
        self.assertEqual(misses, [], f"present-tense lines not flagged: {misses}")


if __name__ == "__main__":
    unittest.main()
