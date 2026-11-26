"""
Unit Tests for Local Somatic Chunk & Reranker Coprocessor.
Milestone CP-1: Local Somatic Chunk & Reranker Coprocessor.
"""

import sys
import unittest
from pathlib import Path

# Ensure repository root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prose_engine.coprocessor.reranker import (
    LocalSomaticReranker,
    RerankResult,
)


class TestLocalSomaticReranker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reranker = LocalSomaticReranker(lazy_load=False)

    def test_model_loading_and_device(self):
        """Model must load and detect available acceleration device (CUDA if present)."""
        self.assertTrue(self.reranker.is_loaded)
        self.assertIn(str(self.reranker.device), ["cuda", "cuda:0", "cpu"])

    def test_dense_encoding_shape_and_normalization(self):
        """Encodes texts into normalized 384-dimensional dense vectors."""
        texts = ["voluptuous curves in peach silk", "acoustic reverberation against bathroom tiles"]
        embeddings = self.reranker.encode(texts, normalize=True)

        self.assertEqual(embeddings.shape, (2, 384))
        # Normalized vectors have unit length (norm == 1.0)
        norm_0 = float(sum(embeddings[0] ** 2) ** 0.5)
        norm_1 = float(sum(embeddings[1] ** 2) ** 0.5)
        self.assertAlmostEqual(norm_0, 1.0, places=4)
        self.assertAlmostEqual(norm_1, 1.0, places=4)

    def test_empty_inputs_handling(self):
        """Handles empty queries and passages cleanly without crashing."""
        self.assertEqual(self.reranker.encode([]).shape, (0, 384))
        self.assertEqual(self.reranker.rank_passages([], []), [])
        self.assertEqual(
            self.reranker.rank_passages(["test query"], []),
            [],
        )

    def test_soft_weighting_modulation(self):
        """
        Soft book weights must modulate raw similarity scores:
        A primary book with weight 1.25 must defeat a damped book (weight 0.05)
        even if the damped book has a raw cosine match.
        """
        queries = ["peach silk kimono robe at vanity mirror"]

        passages = [
            {
                "text": "She wore a peach silk robe and sat brushing her hair in the warm morning light.",
                "book_slug": "brazilian_tales_isaac_goldberg",
                "author": "Isaac Goldberg",
            },
            {
                "text": "She put on her pink silk dressing gown and looked into the Hollywood vanity mirror.",
                "book_slug": "valley_of_the_dolls_jacqueline_susann",
                "author": "Jacqueline Susann",
            },
        ]

        # Primary has weight 1.25, Romance Melodrama is soft-damped to 0.05
        book_weights = {
            "brazilian_tales_isaac_goldberg": 1.25,
            "valley_of_the_dolls_jacqueline_susann": 0.05,
        }

        results = self.reranker.rank_passages(
            queries=queries,
            passages=passages,
            book_weights=book_weights,
            top_k=2,
        )

        self.assertEqual(len(results), 2)
        # Winner must be Brazilian Tales due to soft affinity weighting
        self.assertEqual(results[0].book_slug, "brazilian_tales_isaac_goldberg")
        self.assertGreaterEqual(results[0].book_weight, 1.0)
        self.assertGreater(results[0].effective_score, results[1].effective_score)

        # Jacqueline Susann is damped
        self.assertEqual(results[1].book_slug, "valley_of_the_dolls_jacqueline_susann")
        self.assertEqual(results[1].book_weight, 0.05)
        self.assertLess(results[1].effective_score, 0.10)

    def test_rerank_beat_candidates_integration(self):
        """Verifies high-level beat candidate reranking across representative paragraphs."""
        vector_queries = ["porcelain bowl vibration", "subterranean engine shudder"]
        physical_anchors = ["water ripples", "rusty outboard motor"]

        candidate_books = [
            "guards_guards_swamp_dragon_chronicles_terry_pratchett",
            "dreamcatcher_the_byrus_and_colic_chronicles_stephen_king",
            "star_pamela_anderson",
        ]

        book_paragraphs = {
            "guards_guards_swamp_dragon_chronicles_terry_pratchett": [
                "The standing water in the bowl shivered into tight concentric ripples like a prehistoric warning.",
                "He walked down the cobblestone street under the rain.",
            ],
            "dreamcatcher_the_byrus_and_colic_chronicles_stephen_king": [
                "A subterranean shudder rattled deep in his gut, like an old outboard motor coughing in wet cement.",
                "The snow fell silently across the pine trees of Derry.",
            ],
            "star_pamela_anderson": [
                "She checked her makeup in the mirror and felt a strange shudder of fear.",
            ],
        }

        def dummy_author_resolver(slug: str) -> str:
            if "pratchett" in slug:
                return "Terry Pratchett"
            elif "king" in slug:
                return "Stephen King"
            return "Pamela Anderson"

        book_weights = {
            "guards_guards_swamp_dragon_chronicles_terry_pratchett": 1.25,
            "dreamcatcher_the_byrus_and_colic_chronicles_stephen_king": 1.25,
            "star_pamela_anderson": 0.05,
        }

        ranked = self.reranker.rerank_beat_candidates(
            vector_queries=vector_queries,
            physical_anchors=physical_anchors,
            candidate_books=candidate_books,
            book_paragraphs_lookup=book_paragraphs,
            resolve_author_fn=dummy_author_resolver,
            book_weights=book_weights,
            top_k=2,
        )

        self.assertEqual(len(ranked), 2)
        # Both top results must be from Pratchett or King (primary farce books)
        top_authors = {r.author for r in ranked}
        self.assertTrue(top_authors.issubset({"Terry Pratchett", "Stephen King"}))
        self.assertNotIn("Pamela Anderson", top_authors)


if __name__ == "__main__":
    unittest.main()
