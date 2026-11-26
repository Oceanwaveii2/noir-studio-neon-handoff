"""S3: adversarial guard suite — 45 cases, no invented entity may pass."""

import json
import unittest
from pathlib import Path

from prose_engine.voice.adversarial import check
from prose_engine.voice.world_state import WorldState

FIXTURE = Path("tests/fixtures/guards_adversarial.json")


class AdversarialGuardTests(unittest.TestCase):
    def setUp(self):
        self.world = WorldState.load()
        self.cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]

    def test_fixture_has_enough_cases(self):
        self.assertGreaterEqual(len(self.cases), 40)

    def test_decisions_are_correct(self):
        wrong = []
        for case in self.cases:
            issues = check(case["original"], case["candidate"], self.world)
            if bool(issues) != case["expect_reject"]:
                wrong.append((case["id"], case["expect_reject"], issues))
        accuracy = 1 - len(wrong) / len(self.cases)
        self.assertGreaterEqual(accuracy, 0.95, wrong[:5])
        self.assertEqual(len(wrong), 0, wrong[:5])

    def test_no_invented_entity_is_accepted(self):
        for case in self.cases:
            if case["id"].startswith(("invented_person", "forbidden")):
                self.assertTrue(check(case["original"], case["candidate"], self.world), case["id"])


if __name__ == "__main__":
    unittest.main()
