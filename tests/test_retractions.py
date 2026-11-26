"""Regression test for F10 / F15: retractions lock-in and clean checkout verification."""

import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RetractionTests(unittest.TestCase):
    def test_retractions_document_exists_and_covers_all_claims(self):
        retractions_path = ROOT / "docs" / "RETRACTIONS.md"
        self.assertTrue(retractions_path.is_file(), "docs/RETRACTIONS.md must exist")
        content = retractions_path.read_text(encoding="utf-8")
        for claim in ["0.656", "0.125", "0.525", "0.63"]:
            self.assertIn(claim, content, f"docs/RETRACTIONS.md must document retracted claim: {claim}")

    def test_readme_has_no_retracted_claims(self):
        readme_path = ROOT / "README.md"
        if readme_path.is_file():
            content = readme_path.read_text(encoding="utf-8")
            for claim in ["0.656", "AUC 0.125", "0.525 \u00b1 0.139"]:
                self.assertNotIn(claim, content, f"README.md must not contain retracted claim: {claim}")

    def test_no_hardcoded_retracted_floors_in_engine_gates(self):
        engine_dir = ROOT / "prose_engine"
        for py_file in engine_dir.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            self.assertNotIn("0.63", text, f"Hardcoded retracted floor 0.63 found in {py_file.name}")
            self.assertNotIn("0.656", text, f"Hardcoded retracted metric 0.656 found in {py_file.name}")


if __name__ == "__main__":
    unittest.main()
