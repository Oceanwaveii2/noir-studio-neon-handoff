"""Strength presets: rebuild demands genuinely new sentences, light tolerates a near-copy."""

import unittest

from prose_engine.conditioner import plan_conditioning
from prose_engine.strength import PRESETS, get
from prose_engine.style_engine import STANDARD_DRAMATIC


class FixedProvider:
    model_name = "fixed"

    def __init__(self, text):
        self.text = text

    def generate_rewrite(self, request, prompt):  # noqa: ARG002
        return self.text


ORIGINAL = (
    "The nanites on her arms shimmer like liquid mercury and the seams pop like popcorn. "
    "Her backside swells like a parade float until it takes the end of the couch."
)

NEAR_COPY = (
    "The nanites on her arms shimmer like mercury, and the seams pop like corn. "
    "Her backside swells like a float until it fills the end of the couch."
)

REBUILT = (
    "Under her skin the machines break ranks and run for her hips. The dress gives seam by seam. "
    "She takes the whole end of the couch."
)


def propose(candidate, strength):
    proposals = plan_conditioning(
        ORIGINAL, FixedProvider(candidate), STANDARD_DRAMATIC, strength=strength
    )
    return proposals[0]


class StrengthTests(unittest.TestCase):
    def test_presets_get_stricter(self):
        self.assertGreater(PRESETS["light"].max_overlap, PRESETS["rebuild"].max_overlap)
        self.assertLess(PRESETS["light"].references, PRESETS["rebuild"].references)

    def test_unknown_strength_raises(self):
        with self.assertRaises(ValueError):
            get("turbo")

    def test_rebuild_rejects_near_copy(self):
        proposal = propose(NEAR_COPY, "rebuild")
        self.assertFalse(proposal.accepted)
        self.assertIn("too close", proposal.reason)

    def test_rebuild_accepts_new_writing(self):
        proposal = propose(REBUILT, "rebuild")
        self.assertTrue(proposal.accepted, proposal.reason)

    def test_light_accepts_near_copy(self):
        proposal = propose(NEAR_COPY, "light")
        self.assertTrue(proposal.accepted, proposal.reason)


if __name__ == "__main__":
    unittest.main()
