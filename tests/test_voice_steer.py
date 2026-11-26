"""Steering vector contract (CPU, tiny model)."""

import tempfile
import unittest
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch
from transformers import AutoTokenizer, Qwen2Config, Qwen2ForCausalLM

from prose_engine.voice.style_vector import StyleHook, StyleVector, extract, pairs_from_rewrites


@lru_cache(maxsize=1)
def tiny_model():
    config = Qwen2Config(
        vocab_size=tokenizer().vocab_size, hidden_size=16, intermediate_size=32,
        num_hidden_layers=2, num_attention_heads=2, num_key_value_heads=1,
    )
    model = Qwen2ForCausalLM(config)
    model.eval()
    return model


def tokenizer():
    return AutoTokenizer.from_pretrained("Qwen/Qwen2.5-1.5B-Instruct")


class SteerTests(unittest.TestCase):
    def test_extract_returns_unit_vector(self):
        model = tiny_model()
        tok = tokenizer()
        pairs = [("The room was cold and the lamp hummed.", "A room. A lamp.")]
        vector = extract(model, tok, pairs, layer=1)
        self.assertEqual(vector.vector.shape[0], 16)
        self.assertAlmostEqual(float(np.linalg.norm(vector.vector)), 1.0, places=4)

    def test_save_load_round_trip(self):
        vector = StyleVector(vector=np.ones(8) / np.sqrt(8), layer=3)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v.npz"
            vector.save(path)
            loaded = StyleVector.load(path)
            self.assertEqual(loaded.layer, 3)
            self.assertTrue(np.allclose(loaded.vector, vector.vector))

    def test_hook_changes_logits(self):
        model = tiny_model()
        tok = tokenizer()
        inputs = tok("The room was cold.", return_tensors="pt")
        vector = np.zeros(16, dtype="float32")
        vector[0] = 1.0
        with torch.no_grad():
            baseline = model(**inputs).logits
        with StyleHook(model, vector, 0, alpha=2.0):
            with torch.no_grad():
                steered = model(**inputs).logits
        self.assertFalse(torch.allclose(baseline, steered))

    def test_hook_alpha_zero_is_identity(self):
        model = tiny_model()
        tok = tokenizer()
        inputs = tok("The room was cold.", return_tensors="pt")
        vector = np.ones(16, dtype="float32")
        with torch.no_grad():
            baseline = model(**inputs).logits
        with StyleHook(model, vector, 0, alpha=0.0):
            with torch.no_grad():
                same = model(**inputs).logits
        self.assertTrue(torch.allclose(baseline, same))

    def test_pairs_from_rewrites_skips_empty(self):
        pairs = pairs_from_rewrites(["a", "", "b"], ["x", "y", ""])
        self.assertEqual(pairs, [("a", "x")])


if __name__ == "__main__":
    unittest.main()
