import json
from pathlib import Path
import unittest

import numpy as np

from prose_engine.voice.retrieval_experiment import ExperimentIndex, Passage, Query, allows, parse_fixture


class RetrievalExperimentTests(unittest.TestCase):
    def test_rights_exclusion_precedes_model_and_edition_exclusion_precedes_rerank(self):
        docs = [
            Passage("a", "first", "original_u6", ("hard_cut",), "The empty lift displayed Ground Floor."),
            Passage("b", "first", "original_u6", (), "The queue formed at the lift."),
            Passage("c", "second", "original_u6", ("hard_cut",), "The lift fell; a sign read Floor closed."),
            Passage("d", "first", "blocked_probe", ("hard_cut",), "Denied sentinel"),
            Passage("e", "first", "missing_rights", ("hard_cut",), "Unclassified sentinel"),
        ]

        def encode(texts):
            self.assertTrue(all("sentinel" not in text for text in texts))
            return np.ones((len(texts), 2), dtype=np.float32)

        def rerank(query, texts):
            self.assertEqual(query, "lift floor")
            self.assertEqual(set(texts), {docs[0].text, docs[1].text})
            return [0.0 if text == docs[0].text else 1.0 for text in texts]

        index = ExperimentIndex(docs, encode)
        self.addCleanup(index.close)
        query = Query("q", "first", "hard_cut", "lift floor")
        self.assertEqual(index.rank("no_references", query), [])
        self.assertEqual(set(index.rank("minilm", query)), {"a", "b"})
        self.assertEqual(index.rank("qwen_rerank", query, rerank), ["b", "a"])
        self.assertEqual(index.rank("function_hybrid", Query("q", "missing", "hard_cut", "lift")), [])
        self.assertTrue(allows("original_u6", "rank_local"))
        self.assertFalse(allows("original_u6", "prompt_generation"))
        self.assertFalse(allows("original_u6", "transfer_remote"))
        self.assertFalse(allows("original_u6", "export_text"))

    def test_frozen_queries_and_judgments_use_edition_holdout(self):
        root = Path(__file__).resolve().parents[1]
        fixture = json.loads((root / "eval/u6_reference_fixture.json").read_text(encoding="utf-8"))
        documents, queries, editions, judgments = parse_fixture(fixture)
        held_out = [q for q in queries if editions[q.edition] == "held_out"]
        self.assertEqual(len(held_out), 36)
        self.assertEqual(len({q.edition for q in held_out}), 3)
        self.assertEqual(sum(q.function is None for q in held_out), 6)
        self.assertEqual(len(queries) - len(held_out), 6)
        first = held_out[0]
        wrong_edition = next(p for p in documents if p.edition != first.edition)
        judgments[first.id][wrong_edition.id] = 3
        with self.assertRaisesRegex(ValueError, "wrong-edition"):
            parse_fixture(fixture)

    def test_unknown_tags_keep_plain_hybrid_path(self):
        docs = [
            Passage("a", "edition", "original_u6", (), "An empty shelf displayed a dated receipt."),
            Passage("b", "edition", "original_u6", ("hard_cut",), "The lift fell and the display read Help."),
        ]
        index = ExperimentIndex(docs, lambda texts: np.ones((len(texts), 2), dtype=np.float32))
        self.addCleanup(index.close)
        # FTS ranks the lexical hit first with no function hint. With the
        # function hint both remain eligible; this test also exercises FTS
        # query syntax sanitizing characters.
        query = Query("q", "edition", None, 'shelf "*" :receipt')
        self.assertEqual(index.rank("function_hybrid", query), ["a", "b"])
        self.assertEqual(index.rank("lexical_dense", query), ["a", "b"])
