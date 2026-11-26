"""World state contracts."""

import unittest
from pathlib import Path

from prose_engine.voice.world_state import WorldState


class WorldStateTests(unittest.TestCase):
    def setUp(self):
        self.state = WorldState.load(Path("books/world_state.json"))

    def test_rules_and_cast_load(self):
        self.assertGreaterEqual(len(self.state.rules), 5)
        self.assertIn("Rainee", self.state.characters)
        self.assertIn("Francine", self.state.characters)
        self.assertNotIn("Stan", self.state.characters)

    def test_dad_is_a_violation(self):
        found = self.state.violations("I'm telling Dad!")
        self.assertTrue(found)
        self.assertIn("father", found[0][1])

    def test_husband_is_a_violation(self):
        self.assertTrue(self.state.violations("Her husband walked in."))

    def test_half_fox_is_a_violation(self):
        self.assertTrue(self.state.violations("She is half-fox."))

    def test_clean_scene_passes(self):
        text = "Rainee snaps her fingers. The toilet widens under her. Haley coughs."
        self.assertTrue(self.state.check(text))

    def test_voice_through_a_floor_is_impossible(self):
        found = self.state.plausibility("From the kitchen, Francine hears Rainee upstairs.")
        self.assertTrue(found, "expected a floor-sound violation")

    def test_calling_up_the_stairs_is_fine(self):
        self.assertEqual(self.state.plausibility("Francine calls up the stairs."), [])

    def test_haley_has_no_tail_yet(self):
        self.assertTrue(self.state.plausibility("Haley flicks her tail."))

    def test_resizing_is_allowed(self):
        self.assertEqual(self.state.plausibility("Rainee snaps her fingers; the toilet widens."), [])

    def test_prompt_block_has_canon(self):
        block = self.state.prompt_block()
        self.assertIn("shapeshifter", block)
        self.assertIn("never contradict", block)
        self.assertIn("NOT POSSIBLE HERE", block)
        self.assertIn("allowed, not an error", block)


if __name__ == "__main__":
    unittest.main()
