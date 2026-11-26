"""
StyleVector: an inference-time steering direction.

Contrast pairs are (corpus passage, the model's own neutral rewrite of the same content). The
direction is the difference of mean residual-stream activations at one layer. At generation the
vector is added to the hidden states, either everywhere or (safer) only on the first few generated
tokens.

Nothing here trains. The vector is a file; alpha is a dial; alpha=0 is the untouched model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

try:  # torch is optional at import time so CPU tests can run without it
    import torch
except Exception:  # pragma: no cover
    torch = None


@dataclass
class StyleVector:
    vector: np.ndarray
    layer: int
    method: str = "mean"
    alpha: float = 1.0
    meta: Optional[Dict] = None

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            target,
            vector=self.vector.astype("float32"),
            layer=self.layer,
            method=self.method,
            alpha=self.alpha,
        )
        return target

    @classmethod
    def load(cls, path: str | Path) -> "StyleVector":
        data = np.load(Path(path))
        return cls(
            vector=data["vector"], layer=int(data["layer"]),
            method=str(data["method"]), alpha=float(data["alpha"]),
        )


def _pool(model, tokenizer, text: str, layer: int, max_length: int = 256) -> np.ndarray:
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=max_length)
    inputs = {key: value.to(model.device) for key, value in inputs.items()}
    with torch.no_grad():
        output = model(**inputs, output_hidden_states=True)
    hidden = output.hidden_states[layer + 1][0].float().mean(dim=0)
    return hidden.cpu().numpy()


def extract(
    model,
    tokenizer,
    pairs: Sequence[Tuple[str, str]],
    layer: int = 14,
    method: str = "mean",
) -> StyleVector:
    """Difference of means between the corpus side and the neutral side of every pair."""
    if not pairs:
        raise ValueError("no contrast pairs")
    positive = np.mean([_pool(model, tokenizer, pos, layer) for pos, _neg in pairs], axis=0)
    negative = np.mean([_pool(model, tokenizer, neg, layer) for _pos, neg in pairs], axis=0)
    vector = positive - negative
    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector = vector / norm
    return StyleVector(vector=vector, layer=layer, method=method)


class StyleHook:
    """Context manager adding alpha * vector to a decoder layer's hidden states."""

    def __init__(
        self,
        model,
        vector: np.ndarray,
        layer: int,
        alpha: float = 1.0,
        first_k: Optional[int] = None,
    ):
        if torch is None:
            raise RuntimeError("torch is required for steering")
        self.model = model
        self.vector = torch.tensor(np.asarray(vector, dtype="float32"))
        self.layer = layer
        self.alpha = alpha
        self.first_k = first_k
        self._handle = None

    def _hook(self, module, inputs, output):
        hidden = output[0] if isinstance(output, tuple) else output
        vector = self.vector.to(device=hidden.device, dtype=hidden.dtype)
        steered = hidden.clone()
        if self.first_k:
            steered[:, -self.first_k :, :] = steered[:, -self.first_k :, :] + self.alpha * vector
        else:
            steered = steered + self.alpha * vector
        if isinstance(output, tuple):
            return (steered,) + output[1:]
        return steered

    def __enter__(self):
        self._handle = self.model.model.layers[self.layer].register_forward_hook(self._hook)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._handle is not None:
            self._handle.remove()
            self._handle = None
        return False


def pairs_from_rewrites(
    corpus: Sequence[str], rewrites: Sequence[str]
) -> List[Tuple[str, str]]:
    return [(pos, neg) for pos, neg in zip(corpus, rewrites) if pos.strip() and neg.strip()]
