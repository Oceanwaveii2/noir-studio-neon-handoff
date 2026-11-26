"""S5: comedic treatments, distinctness selection, prompt contract."""

import unittest

from prose_engine.voice.distinctness import Take, select, structural
from prose_engine.voice.vary import TREATMENTS, build_prompt

ORIGINAL = "Rainee set the tray down and looked at the door."


class TreatmentTests(unittest.TestCase):
    def test_five_comedic_treatments(self):
        self.assertEqual(len(TREATMENTS), 5)
        self.assertIn("dignity_loss", TREATMENTS)
        self.assertIn("understatement", TREATMENTS)

    def test_prompt_carries_direction_and_treatment(self):
        prompt = build_prompt(ORIGINAL, "make it worse for her", "deadpan_cut")
        self.assertIn("DIRECTION: make it worse for her", prompt)
        self.assertIn("TREATMENT:", prompt)
        self.assertIn("driest possible line", prompt)
        self.assertIn("Rainee", prompt)


class DistinctnessTests(unittest.TestCase):
    def test_structural_signature_changes(self):
        self.assertNotEqual(structural("Rainee set the tray down."), structural("The tray went down. Rainee looked at the door."))

    def test_select_drops_near_duplicates(self):
        takes = [
            Take("Rainee set the tray down.", "a", [1.0, 0.0]),
            Take("Rainee put the tray down.", "b", [0.99, 0.01]),
            Take("The tray went down. Rainee looked at the door.", "c", [0.0, 1.0]),
        ]
        chosen = select(takes, limit=2, max_similarity=0.85)
        self.assertEqual(len(chosen), 2)
        self.assertIn("c", {take.treatment for take in chosen})
        self.assertNotEqual({take.treatment for take in chosen}, {"a", "b"})


if __name__ == "__main__":
    unittest.main()
