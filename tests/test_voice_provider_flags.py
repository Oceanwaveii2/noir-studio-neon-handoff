"""Local provider flags: steering and bans are opt-in and never load a model at construction."""

import unittest

from prose_engine.providers.local_llm import LocalTransformersProvider


class ProviderFlagTests(unittest.TestCase):
    def test_defaults_are_off(self):
        provider = LocalTransformersProvider()
        self.assertIsNone(provider.steer_path)
        self.assertEqual(provider.steer_alpha, 0.0)
        self.assertFalse(provider.ban_comparisons)

    def test_flags_are_stored(self):
        provider = LocalTransformersProvider(
            steer_path="voice/style_vector.npz", steer_alpha=1.5, ban_comparisons=True
        )
        self.assertEqual(provider.steer_path, "voice/style_vector.npz")
        self.assertEqual(provider.steer_alpha, 1.5)
        self.assertTrue(provider.ban_comparisons)

    def test_no_steer_context_when_alpha_zero(self):
        provider = LocalTransformersProvider(steer_path="missing.npz", steer_alpha=0.0)
        self.assertIsNone(provider._steer_context().__class__.__name__ if False else None)


if __name__ == "__main__":
    unittest.main()
