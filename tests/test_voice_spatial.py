"""Spatial contract: geometry reaches the prompt and the gate."""

import unittest
from pathlib import Path

from prose_engine.voice.spatial import House

SCENE = [
    "INT. KITCHEN — DAY",
    "Francine stacks containers into the fridge.",
    "INT. UPSTAIRS BATHROOM — CONTINUOUS",
    "Rainee sits. The toilet widens under her.",
    "INT. KITCHEN — LATER",
    "Haley walks in.",
]


class SpatialTests(unittest.TestCase):
    def setUp(self):
        self.house = House.load(Path("books/ling_house"))

    def test_rooms_load(self):
        labels = {room.label for room in self.house.rooms}
        self.assertIn("Kitchen / dining", labels)
        self.assertIn("Full bathroom", labels)
        self.assertTrue(any(room.floor == "upper" for room in self.house.rooms))

    def test_find_by_hint(self):
        room = self.house.find("INT. UPSTAIRS BATHROOM — CONTINUOUS")
        self.assertIsNotNone(room)
        self.assertEqual(room.label, "Full bathroom")

    def test_prompt_block_has_dimensions(self):
        block = self.house.prompt_block("INT. KITCHEN — DAY")
        self.assertIn("Kitchen / dining", block)
        self.assertIn("m2", block)

    def test_map_block_lists_floors_and_rooms(self):
        block = self.house.map_block()
        self.assertIn("HOUSE MAP", block)
        self.assertIn("ground:", block)
        self.assertIn("upper:", block)
        self.assertIn("Kitchen / dining", block)

    def test_teleport_without_transition(self):
        chunks = [
            "INT. KITCHEN — DAY",
            "Francine looks at the door.",
            "INT. LIVING ROOM — CONTINUOUS",
            "Francine sits down.",
        ]
        issues = self.house.check_scene(chunks)
        self.assertTrue(any("Francine" in issue and "transition" in issue for issue in issues))

    def test_walk_is_a_transition(self):
        chunks = [
            "INT. KITCHEN — DAY",
            "Francine looks at the door.",
            "INT. LIVING ROOM — CONTINUOUS",
            "Francine walks in and sits down.",
        ]
        self.assertEqual(self.house.check_scene(chunks), [])

    def test_single_paragraph_is_not_inert(self):
        self.assertTrue(self.house.check_scene(["She sits on the toilet in the kitchen."]))

    def test_annotations_are_not_scene_text(self):
        chunks = [
            "INT. BATHROOM — CONTINUOUS",
            "[DIRECTION: Haley watches Rainee.]",
            "Rainee sits.",
        ]
        self.assertEqual(self.house.check_scene(chunks), [])

    def test_fixture_mismatch(self):
        chunks = ["INT. KITCHEN — DAY", "She sits on the toilet."]
        self.assertTrue(any("toilet" in issue for issue in self.house.check_scene(chunks)))


if __name__ == "__main__":
    unittest.main()
