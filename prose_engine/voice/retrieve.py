"""
Style-aware retrieval: retrieve passages by voice, not topic.

Style vectors are stylometric fingerprints (function words, punctuation, sentence shape) z-scored
against the corpus and L2-normalised. Cosine in that space is "sounds like", not "about".
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Dict, List, Sequence

import joblib
import numpy as np

from ..styleprint import fingerprint, load_model


@dataclass
class StyleHit:
    score: float
    text: str
    meta: Dict


class StyleIndex:
    def __init__(self, vectors: np.ndarray, texts: Sequence[str], meta: Sequence[Dict], encode=None,
                 books_dir: str | Path = "books", model_sha256: str | None = None, manifest=None):
        matrix = np.asarray(vectors, dtype="float32")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        self.vectors = matrix / np.maximum(norms, 1e-9)
        self.texts = list(texts)
        self.meta = list(meta)
        self.encode = encode
        self.books_dir = Path(books_dir)
        self.model_sha256 = model_sha256
        self.manifest = manifest

    @classmethod
    def build(cls, books: str | Path = "books") -> "StyleIndex":
        from ..embedding_store import load_index

        root = Path(books)
        index = load_index(root / "vector_index.joblib")
        style_model = load_model(root)
        if style_model is None:
            raise SystemExit("no styleprint; run: python -m prose_engine.styleprint build")
        mean = np.array(style_model["mean"], dtype=float)
        sd = np.array(style_model["sd"], dtype=float)
        vectors = np.clip((np.array([fingerprint(text) for text in index.texts]) - mean) / sd, -3, 3)
        model_file = root / "styleprint.json"
        revision = hashlib.sha256(model_file.read_bytes()).hexdigest()
        meta = [{**entry, "embedding_backend": "stylometric", "embedding_model": "styleprint",
                 "embedding_revision": revision} for entry in index.meta]
        return cls(vectors, index.texts, meta, books_dir=root,
                    model_sha256=revision)

    def query(self, text: str, k: int = 6, encode=None) -> List[StyleHit]:
        encode = encode or self.encode
        if encode is not None:
            vector = np.asarray(encode(text), dtype=float)
            norm = float(np.linalg.norm(vector))
            if norm == 0:
                return []
            scores = self.vectors @ (vector / norm)
            order = np.argsort(-scores)[:k]
            return [StyleHit(float(scores[i]), self.texts[i], self.meta[i]) for i in order]

        model_file = self.books_dir / "styleprint.json"
        if self.model_sha256 and (not model_file.is_file() or
                hashlib.sha256(model_file.read_bytes()).hexdigest() != self.model_sha256):
            raise ValueError("Style model is missing or does not match the index")
        model = load_model(self.books_dir)
        if model is None:
            raise ValueError(f"Style model missing in {self.books_dir}")
        vector = fingerprint(text)
        if model:
            mean = np.array(model["mean"], dtype=float)
            sd = np.array(model["sd"], dtype=float)
            vector = np.clip((vector - mean) / sd, -3, 3)
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            return []
        scores = self.vectors @ (vector / norm)
        order = np.argsort(-scores)[:k]
        return [
            StyleHit(float(scores[index]), self.texts[index], self.meta[index]) for index in order
        ]

    def score(self, text: str, k: int = 3) -> Dict[str, float]:
        hits = self.query(text, k=k)
        if not hits:
            return {"max": 0.0, "mean_top": 0.0}
        values = [hit.score for hit in hits]
        return {"max": max(values), "mean_top": sum(values) / len(values)}

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"vectors": self.vectors, "texts": self.texts, "meta": self.meta,
                     "model_sha256": self.model_sha256, "manifest": self.manifest}, target)
        return target

    @classmethod
    def load(cls, path: str | Path) -> "StyleIndex":
        data = joblib.load(Path(path))
        return cls(data["vectors"], data["texts"], data["meta"], books_dir=Path(path).resolve().parent,
                   model_sha256=data.get("model_sha256"), manifest=data.get("manifest"))


class StyleDrive:
    """Adapter so the conditioner can use style retrieval like the vector drive."""
    similarity_threshold = 0.10

    def __init__(self, index: StyleIndex, profile_id: str = "corpus"):
        from ..reference_policy import legacy_identities
        self.index = legacy_identities(index)
        self.profile_id = profile_id

    def retrieve_passages(self, profile_id, query_text, scene_type=None, max_results=6, influence=None):
        from ..semantic_drive import ReferencePassage

        hits = self.index.query(query_text, k=len(self.index.texts) if influence is not None else max_results)
        if influence is not None:
            from ..influence import select
            hits = [StyleHit(s,t,m) for s,t,m in
                    select([(h.score,h.text,h.meta) for h in hits],max_results,influence)]
        return [
            ReferencePassage(
                passage_id=hit.meta.get("passage_id", f"{hit.meta.get('book', '?')}-{number}"),
                profile_id=profile_id,
                text=hit.text,
                scene_type="style",
                tags=[str(hit.meta.get("book", ""))],
                provenance={key: hit.meta[key] for key in ("source_id", "source_revision", "anchor", "chunker", "embedding_backend", "embedding_model", "embedding_revision") if key in hit.meta},
            )
            for number, hit in enumerate(hits)
        ]

    def score_text(self, text, k=3):
        if not text.strip() or not self.index.texts:
            return {"max": 0.0, "mean_top": 0.0, "count": 0}
        return self.index.score(text, k=k)


def author_features(books: str | Path = "books") -> str:
    """The voice card, if built; empty otherwise (the conditioner appends it separately)."""
    card = Path(books) / "voice_card.md"
    return card.read_text(encoding="utf-8") if card.is_file() else ""
