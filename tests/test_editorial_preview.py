import json
import unittest
from pathlib import Path
from unittest.mock import patch

from prose_engine.editorial_service import Edit, preview, revision
from prose_engine.voice.world_state import WorldState


class EditorialPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(Path("tests/fixtures/editorial_pilot.json").read_text(encoding="utf-8"))
        cls.text = cls.fixture["document"]
        cls.world = WorldState.load(cls.fixture["canon"])
        cls.dialogue, cls.action, cls.variation = cls.fixture["beats"]
        start = cls.text.index(cls.dialogue["expected_text"])
        cls.frozen = ((start, start + len(cls.dialogue["expected_text"])),)

    def edit(self, beat, item):
        start = self.text.index(beat["expected_text"])
        return Edit(beat["id"], start, start + len(beat["expected_text"]),
                    beat["expected_text"], item["replacement"], item["op"])

    def run_preview(self, edit, text=None, base=None, frozen=None):
        text = self.text if text is None else text
        return preview(text, base or revision(text), tuple(edit), self.frozen if frozen is None else frozen, self.world)

    def test_locked_conflict_remains_visible(self):
        result = self.run_preview([self.edit(self.dialogue, self.dialogue["proposals"][0])])
        self.assertEqual(result.status, "BLOCKED_FROZEN_SPAN")
        self.assertEqual(result.candidate, self.text)
        self.assertTrue(any(i.rule == "rule_no_husband" for i in result.baseline_issues))

    def test_invalid_and_safe_action(self):
        safe, bad = self.action["proposals"]
        blocked = self.run_preview([self.edit(self.action, bad)])
        self.assertEqual(blocked.status, "BLOCKED_NEW_CANON_ISSUE")
        self.assertTrue(any(i.rule == "rule_no_smith_surname" for i in blocked.new_issues))
        result = self.run_preview([self.edit(self.action, safe)])
        self.assertEqual(result.status, "ELIGIBLE_FOR_REVIEW")
        self.assertEqual(result.author_decision, "pending")
        self.assertTrue(result.baseline_issues)

    def test_variation_candidate_reaches_review(self):
        result = self.run_preview([self.edit(self.variation, self.variation["proposals"][0])])
        self.assertEqual(result.status, "ELIGIBLE_FOR_REVIEW")
        self.assertEqual(result.author_decision, "pending")
        self.assertTrue(result.baseline_issues)

    def test_same_rule_new_occurrence_is_detected(self):
        edit = self.edit(self.action, self.action["proposals"][0])
        edit = Edit(edit.span_id, edit.start, edit.end, edit.expected,
                    edit.replacement + " Her husband arrived.")
        result = self.run_preview([edit])
        self.assertEqual(result.status, "BLOCKED_NEW_CANON_ISSUE")
        self.assertTrue(any(i.rule == "rule_no_husband" for i in result.new_issues))

    def test_invalid_requests(self):
        e = self.edit(self.action, self.action["proposals"][0])
        self.assertEqual(self.run_preview([e], base="old").status, "STALE_REVISION")
        self.assertEqual(self.run_preview([Edit("x", e.start, e.end, "wrong", "")]).status, "EXPECTED_TEXT_MISMATCH")
        self.assertEqual(self.run_preview([Edit("x", -1, 1, "", "")]).status, "INVALID_RANGE")
        self.assertEqual(self.run_preview([Edit("x", e.start, e.end, e.expected, "", "insert")]).status, "UNSUPPORTED_OPERATION")
        self.assertEqual(self.run_preview([e, Edit("y", e.start, e.end, e.expected, "")]).status, "OVERLAPPING_EDITS")

    def test_unicode_offsets_and_determinism(self):
        text = "Élan 🦊 waits."
        e = Edit("u", 0, 4, "Élan", "Elle")
        a = self.run_preview([e], text=text, frozen=())
        self.assertEqual(a.candidate, "Elle 🦊 waits.")
        self.assertEqual(a, self.run_preview([e], text=text, frozen=()))

    def test_negated_and_repeated_matches(self):
        text = "She has no husband. Her husband arrived."
        e = Edit("a", 0, 3, "She", "Haley")
        result = self.run_preview([e], text=text, frozen=())
        self.assertEqual(result.status, "ELIGIBLE_FOR_REVIEW")
        husbands = [i for i in result.baseline_issues if i.rule == "rule_no_husband"]
        self.assertEqual(len(husbands), 1)
        self.assertEqual(husbands[0].start, text.rindex("husband"))

    def test_preview_does_not_write_files(self):
        e = self.edit(self.action, self.action["proposals"][0])
        with patch("builtins.open", side_effect=AssertionError("unexpected file access")), \
             patch.object(Path, "open", side_effect=AssertionError("unexpected file access")):
            self.assertEqual(self.run_preview([e]).status, "ELIGIBLE_FOR_REVIEW")


if __name__ == "__main__":
    unittest.main()
