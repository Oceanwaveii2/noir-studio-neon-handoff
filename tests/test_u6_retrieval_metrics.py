import unittest
from tools.eval_retrieval_ids import evaluate


class RetrievalScoringTests(unittest.TestCase):
    def test_rank_and_recall_with_two_relevant_items(self):
        result = evaluate({"q": {"a": 3, "b": 1, "c": 0}}, {"q": ["c", "a", "x", "b"]})
        self.assertEqual(result["query_count"], 1)
        self.assertEqual(result["mean_recall_at_5"], 1.0)
        self.assertGreater(result["mean_ndcg_at_5"], 0)
        self.assertLess(result["mean_ndcg_at_5"], 1)

    def test_empty_run_and_missing_queries(self):
        self.assertEqual(evaluate({"q": {"a": 1}}, {"q": []})["mean_recall_at_5"], 0)
        with self.assertRaises(ValueError):
            evaluate({"q": {"a": 1}}, {})
        with self.assertRaises(ValueError):
            evaluate({"q": {"a": 1}}, {"q": ["a", "a"]})
        with self.assertRaises(ValueError):
            evaluate({"q": {"a": 0}}, {"q": ["a"]})
