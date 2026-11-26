"""
Transformer embedding backend for the vector index.

Same interface as `vector_store.VectorIndex` (query / score / save / load), but passages are
embedded with a real sentence-transformer model instead of TF-IDF + SVD. The model is loaded
lazily on first search and identified by name in the index file, so an index is portable
between machines as long as the model is installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import joblib
import numpy as np

DEFAULT_MODEL = "all-MiniLM-L6-v2"


@dataclass
class EmbeddingIndex:
    texts: List[str]
    meta: List[Dict]
    vectors: np.ndarray
    model_name: str = DEFAULT_MODEL
    _model: Any = field(default=None, repr=False)
    manifest: Any = None

    def _encoder(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            artifacts = (self.manifest or {}).get("encoder_artifacts")
            if artifacts:
                from .library_indexes import model_artifacts
                if model_artifacts(artifacts["repository"], artifacts["revision"]) != artifacts:
                    raise ValueError("Topic model artifacts changed since index build")
            self._model = SentenceTransformer(
                artifacts["repository"] if artifacts else self.model_name,
                revision=artifacts["revision"] if artifacts else None, local_files_only=True)
        return self._model

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        return self._encoder().encode(
            list(texts),
            batch_size=64,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).astype("float32")

    def query(self, text: str, k: int = 3, influence=None) -> List[Tuple[float, str, Dict]]:
        scores = self.vectors @ self._encode([text])[0]
        if influence is not None:
            from .influence import select

            order = np.argsort(-scores)
            scored = [
                (float(scores[index]), self.texts[index], self.meta[index]) for index in order
            ]
            return select(scored, k, influence)
        top = np.argsort(-scores)[:k]
        return [(float(scores[index]), self.texts[index], self.meta[index]) for index in top]

    def score(self, text: str, k: int = 3) -> Dict[str, float]:
        scores = self.vectors @ self._encode([text])[0]
        top = np.sort(scores)[-k:]
        return {"max": float(scores.max()), "mean_top": float(top.mean())}

    @classmethod
    def build(cls, chunks: Sequence[Dict], model_name: str = DEFAULT_MODEL) -> "EmbeddingIndex":
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_name)
        vectors = model.encode(
            [chunk["text"] for chunk in chunks],
            batch_size=64,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=True,
        ).astype("float32")
        meta = [{**chunk, "embedding_backend": "transformer", "embedding_model": model_name,
                 "embedding_revision": "unversioned"} for chunk in chunks]
        return cls([chunk["text"] for chunk in chunks], meta, vectors, model_name, model)

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "backend": "transformer",
                "texts": self.texts,
                "meta": self.meta,
                "vectors": self.vectors,
                "model_name": self.model_name,
                "manifest": self.manifest,
            },
            target,
            compress=3,
        )
        return target

    @classmethod
    def load(cls, path: str | Path) -> "EmbeddingIndex":
        data = joblib.load(Path(path))
        return cls(data["texts"], data["meta"], data["vectors"], data["model_name"], manifest=data.get("manifest"))


def load_index(path: str | Path):
    """Loads either backend from the same index file."""
    data = joblib.load(Path(path))
    if data.get("backend") == "transformer":
        return EmbeddingIndex(data["texts"], data["meta"], data["vectors"], data["model_name"], manifest=data.get("manifest"))
    from .vector_store import VectorIndex

    return VectorIndex(
        data["texts"], data["meta"], data["vectors"], data["vectorizer"], data["svd"], data["dim"]
    )
