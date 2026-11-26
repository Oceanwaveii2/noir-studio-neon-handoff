"""
Local Somatic Chunk & Reranker Coprocessor.
Milestone CP-1: Local Somatic Chunk & Reranker Coprocessor.

Uses `sentence-transformers/all-MiniLM-L6-v2` on local CUDA (RTX 4080 Super)
to perform sub-second dense semantic reranking across authorized book passages:
  - Generates 384-dimensional dense semantic vectors for beat physical queries and anchors.
  - Computes cosine similarity against candidate book paragraphs.
  - Modulates raw similarity scores by the book's soft affinity weight (M-PE2):
      effective_score = cosine_similarity * book_weight
  - Returns top-ranked somatic excerpts to feed Gemini with clean, targeted context.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np


@dataclass
class RerankResult:
    author: str
    book_slug: str
    excerpt: str
    query_match: str
    raw_similarity: float
    book_weight: float
    effective_score: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LocalSomaticReranker:
    """
    Sub-second local coprocessor that embeds and ranks somatic/physical book passages
    using sentence-transformers/all-MiniLM-L6-v2 on GPU.
    """

    MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        lazy_load: bool = True,
    ):
        self.model_name = model_name or self.MODEL_NAME
        self.device = device
        self._model = None
        self._embedding_cache: Dict[str, np.ndarray] = {}

        if not lazy_load:
            self._ensure_loaded()

    def _ensure_loaded(self) -> Any:
        if self._model is not None:
            return self._model

        import torch
        from sentence_transformers import SentenceTransformer

        if self.device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # Suppress noisy unauthenticated HF warnings if cached locally
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def encode(self, texts: Sequence[str], normalize: bool = True) -> np.ndarray:
        """Encodes texts into normalized dense embedding vectors."""
        model = self._ensure_loaded()
        if not texts:
            return np.empty((0, 384), dtype=np.float32)
        embeddings = model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=normalize,
            show_progress_bar=False,
        )
        return embeddings

    def rank_passages(
        self,
        queries: Sequence[str],
        passages: Sequence[Dict[str, Any]],
        book_weights: Optional[Dict[str, float]] = None,
        top_k: int = 5,
    ) -> List[RerankResult]:
        """
        Ranks candidate passages against physical queries modulated by soft book weights.

        Args:
            queries: Physical motifs / vector queries (e.g. ['peach silk robe', 'porcelain bowl vibration']).
            passages: List of dicts with keys: {'text': str, 'book_slug': str, 'author': str}.
            book_weights: Optional mapping of {book_slug: weight} from M-PE2.
            top_k: Maximum number of ranked results to return.

        Returns:
            List of RerankResult objects sorted in descending order of effective_score.
        """
        if not queries or not passages:
            return []

        weights = book_weights or {}

        # 1. Encode queries into normalized dense vectors
        q_embeddings = self.encode(queries, normalize=True)
        # Average query representation for multi-anchor fusion
        q_centroid = np.mean(q_embeddings, axis=0)
        q_centroid = q_centroid / (np.linalg.norm(q_centroid) + 1e-9)

        # 2. Extract and encode passages
        texts = [p.get("text", "") for p in passages]
        p_embeddings = self.encode(texts, normalize=True)

        # 3. Compute cosine similarities (dot product since vectors are normalized)
        cos_sims = np.dot(p_embeddings, q_centroid)

        results: List[RerankResult] = []
        for idx, p in enumerate(passages):
            raw_sim = float(cos_sims[idx])
            slug = p.get("book_slug", "unknown")
            author = p.get("author", "Unknown")
            raw_text = p.get("text", "").strip().replace("\n", " ")

            # Clean excerpt to 280 characters
            excerpt = raw_text[:277] + "..." if len(raw_text) > 280 else raw_text

            # Modulate by soft affinity weight
            w = float(weights.get(slug, 1.0))
            effective_score = round(raw_sim * w, 4)

            # Find closest single query match for attribution
            best_q_idx = int(np.argmax(np.dot(q_embeddings, p_embeddings[idx])))
            best_q = queries[best_q_idx]

            results.append(
                RerankResult(
                    author=author,
                    book_slug=slug,
                    excerpt=excerpt,
                    query_match=best_q,
                    raw_similarity=round(raw_sim, 4),
                    book_weight=w,
                    effective_score=effective_score,
                )
            )

        # 4. Sort by effective_score descending
        results.sort(key=lambda r: r.effective_score, reverse=True)
        return results[:top_k]

    def rerank_beat_candidates(
        self,
        vector_queries: List[str],
        physical_anchors: List[str],
        candidate_books: List[str],
        book_paragraphs_lookup: Dict[str, List[str]],
        resolve_author_fn: Any,
        book_weights: Optional[Dict[str, float]] = None,
        top_k: int = 5,
    ) -> List[RerankResult]:
        """
        High-level beat reranking: gathers paragraphs from authorized books,
        ranks them against vector queries and physical anchors, and returns the top matches.
        """
        combined_queries = list(dict.fromkeys(vector_queries + physical_anchors))
        if not combined_queries:
            combined_queries = ["physical comedy and somatic details"]

        passages: List[Dict[str, Any]] = []
        for slug in candidate_books:
            paras = book_paragraphs_lookup.get(slug, [])
            author = resolve_author_fn(slug)
            # Take up to 20 representative paragraphs per book to keep reranking fast
            for p in paras[:20]:
                if len(p.split()) >= 8:
                    passages.append({
                        "text": p,
                        "book_slug": slug,
                        "author": author,
                    })

        return self.rank_passages(
            queries=combined_queries,
            passages=passages,
            book_weights=book_weights,
            top_k=top_k,
        )
