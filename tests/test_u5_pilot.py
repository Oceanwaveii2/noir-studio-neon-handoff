from copy import deepcopy
import unittest

from prose_engine.editorial_service import revision
from prose_engine.voice.spatial import House
from prose_engine.voice.world_state import WorldState
from tools.review_pilot import ROOT, freeze, manuscript_spans, read_json, report


class AuthorPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = read_json(ROOT / "eval/u5_pilot_spec.json")
        cls.source = (ROOT / cls.spec["source"]).read_bytes().decode("utf-8")
        cls.world = WorldState.load()
        cls.house = House.load()
        cls.public, cls.private, cls.receipt = freeze(cls.spec, cls.source, cls.world, cls.house)

    def test_actual_manuscript_pairs_are_anchored_and_scene_separated(self):
        self.assertEqual(revision(self.source), self.receipt["source_sha256"])
        self.assertIn("\r\n", self.source)
        self.assertEqual(len(self.public["cases"]), 40)
        self.assertEqual(self.receipt["development_count"], 7)
        self.assertEqual(set(self.receipt["held_out_scenes"]), {"1", "3", "4", "5", "7"})
        self.assertEqual(self.receipt["author_review"], "PENDING")
        self.assertTrue(all(g["result"] == "ELIGIBLE_FOR_REVIEW" for g in self.receipt["automatic_gates"]))
        for row in self.public["cases"]:
            key = self.private["case_key"][row["token"]]
            self.assertNotIn("scene_id", row)
            self.assertNotIn("candidate", row)
            paragraph = manuscript_spans(self.source)[key["paragraph"]]
            self.assertEqual(revision(paragraph["text"]), key["original_sha256"])
            self.assertFalse(paragraph["protected"])
            self.assertEqual(row["split"], "held_out")
            self.assertNotEqual(row["option_a"], row["option_b"])

    def test_source_drift_and_protected_dialogue_do_not_enter_review(self):
        with self.assertRaisesRegex(ValueError, "frozen pilot source"):
            freeze(self.spec, self.source + "\n", self.world, self.house)
        spec = deepcopy(self.spec)
        spans = manuscript_spans(self.source)
        index = next(i for i, p in enumerate(spans) if p["scene"] == "1" and
                     p["text"].startswith('"Rainee, let\'s go!'))
        spec["edits"].append({"scene": "1", "paragraph": index,
                              "before": "Rainee, let's go!", "after": "Rainee, stay here."})
        public, _, receipt = freeze(spec, self.source, self.world, self.house)
        self.assertEqual(len(public["cases"]), 40)
        self.assertEqual(receipt["automatic_gates"][-1]["result"], "BLOCKED_FROZEN_SPAN")

    def test_named_votes_only_and_effort_uses_complete_pairs(self):
        first, second = self.public["cases"][:2]
        decisions = {"schema_version": 1, "fingerprint": self.public["fingerprint"],
                     "reviewer": "Synthetic test reviewer", "decisions": []}
        self.assertEqual(report(self.private, decisions)["status"], "pending")
        key = self.private["case_key"][first["token"]]
        candidate_side = "a" if key["option_a"] == "candidate" else "b"
        decisions["decisions"].append({
            "token": first["token"], "choice": candidate_side,
            "options": {"a": {"usable": True, "seconds": 7, "final_text": first["option_a"] + "!"},
                        "b": {"usable": True, "seconds": 4, "final_text": first["option_b"]}},
        })
        decisions["decisions"].append({"token": second["token"], "choice": "tie",
                                       "options": {"a": {"usable": False}}})
        result = report(self.private, decisions)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["author_preferences"], {"accept": 1, "keep_original": 0, "tie": 1, "reject": 0})
        self.assertEqual(result["paired_usability"]["denominator"], 1)
        self.assertEqual(result["paired_usability"]["counts"]["both"], 1)
        self.assertEqual(result["paired_effort"]["edit_distance"]["denominator"], 1)
        self.assertEqual(result["paired_effort"]["edit_distance"]["median_paired_change"],
                         1 if candidate_side == "a" else -1)
        self.assertEqual(result["paired_effort"]["seconds_to_usable"]["median_paired_change"],
                         3 if candidate_side == "a" else -3)
        self.assertIsNone(result["paired_usability"]["scene_bootstrap_95_exploratory"])
        with self.assertRaisesRegex(ValueError, "named reviewer"):
            report(self.private, {**decisions, "reviewer": " "})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            report(self.private, {**decisions, "decisions": decisions["decisions"] * 2})
