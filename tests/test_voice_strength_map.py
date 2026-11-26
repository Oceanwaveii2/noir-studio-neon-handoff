"""Strength map and freeze contracts."""

import json
import tempfile
import unittest
from pathlib import Path

from prose_engine.voice.strength_map import (
    StrengthMap,
    dialogue_lines,
    missing_frozen,
    policy,
)


class PolicyTests(unittest.TestCase):
    def test_bands(self):
        self.assertTrue(policy(0.0).skip)
        self.assertEqual(policy(0.3).preset, "light")
        self.assertEqual(policy(0.6).preset, "standard")
        self.assertEqual(policy(1.0).preset, "rebuild")
        self.assertFalse(policy(1.0).skip)

    def test_clamped(self):
        self.assertEqual(policy(-1).strength, 0.0)
        self.assertEqual(policy(2).strength, 1.0)


class StrengthMapTests(unittest.TestCase):
    def setUp(self):
        self.mapping = StrengthMap(
            default=1.0,
            rules=[
                __import__("prose_engine.voice.strength_map", fromlist=["Rule"]).Rule("range:0-2", 0.0),
                __import__("prose_engine.voice.strength_map", fromlist=["Rule"]).Rule("contains:dialogue", 0.2),
            ],
        )

    def test_range_freezes(self):
        self.assertTrue(self.mapping.policy_for(1, "any text").skip)

    def test_contains_selector(self):
        self.assertEqual(self.mapping.strength_for(9, "a dialogue line"), 0.2)

    def test_default_applies(self):
        self.assertEqual(self.mapping.strength_for(9, "plain narration"), 1.0)

    def test_load_from_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.json"
            path.write_text(json.dumps({"default": 0.6, "rules": [{"selector": "index:0", "strength": 0.0}]}), encoding="utf-8")
            loaded = StrengthMap.load(path)
            self.assertTrue(loaded.policy_for(0, "x").skip)
            self.assertEqual(loaded.policy_for(1, "x").preset, "standard")


class FreezeTests(unittest.TestCase):
    def test_dialogue_detection(self):
        paragraphs = ["- Don't touch this line.", "Narration continues.", '"Another line."']
        self.assertEqual(len(dialogue_lines(paragraphs)), 2)

    def test_missing_frozen_detects_drop(self):
        self.assertEqual(missing_frozen("Keep this line. And more.", "And more.", ["Keep this line."]), ["Keep this line."])

    def test_present_frozen_passes(self):
        self.assertEqual(missing_frozen("Keep this line.", "Keep this line. Exactly.", ["Keep this line."]), [])


if __name__ == "__main__":
    unittest.main()
