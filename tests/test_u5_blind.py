import unittest
from tools.blind_evaluation import prepare


class BlindEvaluationTests(unittest.TestCase):
    def test_stable_blind_labels_and_scene_split(self):
        cases = [
            {"id":"one","scene_id":"s1","original":"Original one","candidate":"Revision one"},
            {"id":"two","scene_id":"s2","original":"Original two","candidate":"Revision two"},
        ]
        result = prepare(cases, {"s1":"development", "s2":"held_out"}, "fixed")
        self.assertEqual(result, prepare(cases, {"s1":"development", "s2":"held_out"}, "fixed"))
        for row in result["presentation"]:
            self.assertEqual(set(row), {"token", "split", "option_a", "option_b"})
            mapping = result["key"][row["token"]]
            self.assertEqual({mapping["option_a"], mapping["option_b"]}, {"original","candidate"})
        self.assertEqual({row["split"] for row in result["presentation"]}, {"development","held_out"})

    def test_invalid_scene_and_duplicate_ids_fail(self):
        case = {"id":"one","scene_id":"s1","original":"a","candidate":"b"}
        with self.assertRaises(ValueError):
            prepare([case, case], {"s1":"development","s2":"held_out"}, "fixed")
        with self.assertRaises(ValueError):
            prepare([case], {"s1":"held_out"}, "fixed")
