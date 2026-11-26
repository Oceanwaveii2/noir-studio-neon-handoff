"""S7: the quality budget can fail."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class QualityBudgetTests(unittest.TestCase):
    def test_budget_passes_by_default(self):
        run = subprocess.run(
            [sys.executable, "tools/quality_budget.py"], capture_output=True, text=True, cwd=ROOT
        )
        self.assertEqual(run.returncode, 0, run.stdout[-800:])
        self.assertIn("PASS", run.stdout)

    def test_deliberate_violation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            budget = json.loads((ROOT / "ci_budget.json").read_text(encoding="utf-8"))
            budget["max_canon_violations"] = -1
            path = Path(tmp) / "budget.json"
            path.write_text(json.dumps(budget), encoding="utf-8")
            run = subprocess.run(
                [sys.executable, "tools/quality_budget.py", "--budget-file", str(path)],
                capture_output=True, text=True, cwd=ROOT,
            )
            self.assertEqual(run.returncode, 1)
            self.assertIn("QUALITY BUDGET FAILED", run.stdout)


if __name__ == "__main__":
    unittest.main()
