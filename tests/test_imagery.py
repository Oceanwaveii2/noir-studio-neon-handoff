"""Imagery retention contract."""

import unittest

from prose_engine.imagery import mask, retained, vehicles


class ImageryTests(unittest.TestCase):
    def test_extracts_comparison_vehicles(self):
        text = "The seams popped like popcorn and her tail moved like a parade float."
        found = vehicles(text)
        self.assertIn("popcorn", found)
        self.assertIn("parade", found)

    def test_detects_reworded_reuse(self):
        original = "The seams pop like popcorn. Her tail trailed like a parade float."
        candidate = "The seams burst like popcorn kernels. Her tail dragged like a parade balloon."
        self.assertTrue(retained(original, candidate))

    def test_new_imagery_is_not_retention(self):
        original = "The seams pop like popcorn."
        candidate = "The seams split with a series of small explosions."
        self.assertEqual(retained(original, candidate), set())

    def test_participle_is_not_an_image(self):
        original = "Nanites shimmer like liquid mercury, racing up her arms."
        candidate = "Nanites race up her arms in a metallic rush."
        self.assertEqual(retained(original, candidate), set())

    def test_mask_removes_comparisons(self):
        masked = mask("She swelled like a parade float and the seams popped like popcorn.")
        self.assertNotIn("popcorn", masked)
        self.assertIn("[image removed]", masked)


if __name__ == "__main__":
    unittest.main()
