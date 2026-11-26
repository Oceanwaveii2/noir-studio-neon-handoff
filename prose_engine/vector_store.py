"""
Small vector database over the reference books.

Passages are chunked from the ten books, embedded with TF-IDF + Truncated SVD (latent
semantic analysis — a compact, offline "machine learning" index), L2-normalised, and searched
by cosine similarity. It is the retrieval layer SemanticDrive was documented to be, without a
network or a model download.

    python -m prose_engine corpus vectors --books books --out books/vector_index.joblib
    python -m prose_engine reference --file draft.md --flagged --books books
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import joblib
import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from .diagnostics import ProseDiagnosticsAnalyzer as D
from .semantic_drive import ReferencePassage

TARGET_WORDS = 90
MIN_WORDS = 25


def chunk_books(books, target_words: int = TARGET_WORDS) -> List[Dict]:
    """Splits each book into ~90-word chunks, aligned to sentence boundaries."""
    chunks: List[Dict] = []
    for book in books:
        source_revision = hashlib.sha256(book.text.encode("utf-8")).hexdigest()
        ordinal = 0
        sentences = D.split_into_sentences(book.text)
        current: List[str] = []
        words = 0
        for sentence in sentences:
            current.append(sentence)
            words += len(sentence.split())
            if words >= target_words:
                text = " ".join(current)
                if len(text.split()) >= MIN_WORDS:
                    chunks.append(_chunk_record(book, source_revision, ordinal, text))
                    ordinal += 1
                current, words = [], 0
        if current and words >= MIN_WORDS:
            chunks.append(_chunk_record(book, source_revision, ordinal, " ".join(current)))
    return chunks


def _chunk_record(book, revision, ordinal, text):
    identity = hashlib.sha256(json.dumps([book.slug, revision, ordinal], ensure_ascii=False).encode()).hexdigest()
    return {"book": book.slug, "title": book.title, "text": text,
            "source_id": book.slug, "source_revision": revision, "passage_id": "passage:" + identity,
            "anchor": {"chunk_ordinal": ordinal}, "chunker": "sentence-words-v1"}


@dataclass
class VectorIndex:
    texts: List[str]
    meta: List[Dict]
    vectors: np.ndarray
    vectorizer: TfidfVectorizer
    svd: TruncatedSVD
    dim: int

    @classmethod
    def build(cls, chunks: Sequence[Dict], dim: int = 256) -> "VectorIndex":
        texts = [chunk["text"] for chunk in chunks]
        vectorizer = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
            min_df=2,
            max_features=50_000,
            sublinear_tf=True,
        )
        matrix = vectorizer.fit_transform(texts)
        dim = max(2, min(dim, min(matrix.shape) - 1))
        svd = TruncatedSVD(n_components=dim, random_state=0)
        vectors = normalize(svd.fit_transform(matrix)).astype("float32")
        meta = [{**chunk, "embedding_backend": "lsa", "embedding_model": "tfidf-svd",
                 "embedding_revision": "unversioned"} for chunk in chunks]
        return cls(texts, meta, vectors, vectorizer, svd, dim)

    def query(self, text: str, k: int = 3, influence=None) -> List[Tuple[float, str, Dict]]:
        query = normalize(self.svd.transform(self.vectorizer.transform([text])))[0]
        scores = self.vectors @ query
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
        """How close the text sits to the corpus: max and mean top-k cosine similarity."""
        query = normalize(self.svd.transform(self.vectorizer.transform([text])))[0]
        scores = self.vectors @ query
        top = np.sort(scores)[-k:]
        return {"max": float(scores.max()), "mean_top": float(top.mean())}

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "texts": self.texts,
                "meta": self.meta,
                "vectors": self.vectors,
                "vectorizer": self.vectorizer,
                "svd": self.svd,
                "dim": self.dim,
            },
            target,
            compress=3,
        )
        return target

    @classmethod
    def load(cls, path: str | Path) -> "VectorIndex":
        data = joblib.load(Path(path))
        return cls(
            data["texts"],
            data["meta"],
            data["vectors"],
            data["vectorizer"],
            data["svd"],
            data["dim"],
        )


class VectorSemanticDrive:
    """Drop-in replacement for SemanticDrive backed by the vector index."""
    similarity_threshold = 0.10

    def __init__(self, index: VectorIndex, profile_id: str = "corpus"):
        from .reference_policy import legacy_identities
        self.index = legacy_identities(index) if all(hasattr(index, x) for x in ("meta","texts","vectors")) else index
        self.profile_id = profile_id

    def retrieve_passages(
        self,
        profile_id: str,
        query_text: str,
        scene_type: str | None = None,
        max_results: int = 2,
        influence=None,
    ) -> List[ReferencePassage]:
        hits = self.index.query(query_text, k=max_results, influence=influence)
        return [
            ReferencePassage(
                passage_id=meta.get("passage_id", f"{meta['book']}-{index}"),
                profile_id=profile_id,
                text=text,
                scene_type="vector",
                tags=[meta["book"]],
                provenance={key: meta[key] for key in ("source_id", "source_revision", "anchor", "chunker", "embedding_backend", "embedding_model", "embedding_revision") if key in meta},
            )
            for index, (_score, text, meta) in enumerate(hits)
        ]

    def score_text(self, text, k=3):
        if not text.strip() or not self.index.texts:
            return {"max": 0.0, "mean_top": 0.0, "count": 0}
        return self.index.score(text, k=k)
