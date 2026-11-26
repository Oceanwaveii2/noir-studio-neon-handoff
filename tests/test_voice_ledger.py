"""Fluent ledger: order, requirements, missing beats."""

import unittest
from pathlib import Path

from prose_engine.voice.ledger import BeatPlan, sections

SCENE = """INT. LING KITCHEN — DAY

Francine packs.

INT. RAINEE'S BEDROOM — CONTINUOUS

Rainee dresses.

INT. UPSTAIRS HALLWAY — CONTINUOUS

Haley crosses.

INT. BATHROOM — CONTINUOUS

Rainee sits.

INT. DOWNSTAIRS — CONTINUOUS

Francine calls.
"""


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.plan = BeatPlan.load(Path("books/editorial_notes.json"))

    def test_plan_loads(self):
        self.assertGreaterEqual(len(self.plan.beats), 5)
        self.assertTrue(self.plan.initial)

    def test_ordered_scene_passes(self):
        result = self.plan.validate(sections(SCENE))
        self.assertEqual(result["issues"], [])

    def test_missing_beat_is_reported(self):
        text = SCENE.replace("INT. UPSTAIRS HALLWAY — CONTINUOUS", "INT. RAINEE'S BEDROOM — LATER")
        text = text.replace("Haley crosses.", "Rainee waits.")
        result = self.plan.validate(sections(text))
        self.assertTrue(any("hallway" in issue and "missing" in issue for issue in result["issues"]))

    def test_unmet_requirement_is_reported(self):
        off_order = """INT. UPSTAIRS HALLWAY — CONTINUOUS

Haley crosses.

INT. LING KITCHEN — DAY

Francine packs.
"""
        result = self.plan.validate(sections(off_order))
        self.assertTrue(any("requires" in issue for issue in result["issues"]))

    def test_requires_block_mentions_fluents(self):
        block = self.plan.requires_block("hallway")
        self.assertIn("at:Rainee:bathroom", block)
        self.assertIn("prop:door:closed", block)


if __name__ == "__main__":
    unittest.main()
