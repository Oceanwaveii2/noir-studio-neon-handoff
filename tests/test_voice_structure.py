"""Scene contract, story bible and epistemic ledger contracts."""

import tempfile
import unittest
from pathlib import Path

from prose_engine.voice.bible import Bible, Character, Prop
from prose_engine.voice.epistemic import Ledger
from prose_engine.voice.scene import Contract


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.contract = Contract(
            scene_id="ling_porch",
            pov="rainee",
            setting="INT. LING HOUSE - ENTRANCE HALL",
            beat="Rainee arrives",
            facts=["the sedan is at the curb"],
            forbidden=["she teleports"],
            state_out={"rainee": "inside"},
        )

    def test_missing_fact_is_a_violation(self):
        violations = self.contract.check("Rainee walks in. The room smells of lilac.")
        self.assertTrue(any(v.rule == "missing_fact" for v in violations))

    def test_complete_paragraph_passes(self):
        text = "Rainee stands in the hall. The sedan is at the curb."
        violations = [v for v in self.contract.check(text) if v.rule != "pov_absent"]
        self.assertEqual(violations, [])

    def test_forbidden_phrase_is_a_violation(self):
        text = "Rainee stands in the hall. The sedan is at the curb. She teleports."
        self.assertTrue(any(v.rule == "forbidden" for v in self.contract.check(text)))

    def test_prompt_block_lists_facts(self):
        block = self.contract.prompt_block()
        self.assertIn("the sedan is at the curb", block)
        self.assertIn("forbidden", block)

    def test_save_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scene.json"
            self.contract.save(path)
            loaded = Contract.load(path)
            self.assertEqual(loaded.scene_id, "ling_porch")
            self.assertEqual(loaded.facts, ["the sedan is at the curb"])


class BibleTests(unittest.TestCase):
    def setUp(self):
        self.bible = Bible(
            characters={"haley": Character(traits=["black hair"], forbidden_claims=["hair vanished"])},
            props={"compact_mirror": Prop(held_by="francine", since=2)},
            facts=["the Lings live at the end of the cul-de-sac"],
        )

    def test_forbidden_claim_flagged(self):
        violations = self.bible.check("Haley's hair vanished in the dome.")
        self.assertTrue(any(v.rule == "forbidden_claim" for v in violations))

    def test_clean_text_passes(self):
        self.assertEqual(self.bible.check("Haley's black hair stayed black."), [])

    def test_diff_detects_lost_fact(self):
        before = "The Lings live at the end of the cul-de-sac."
        after = "The Lings live nearby."
        self.assertTrue(any(v.rule == "lost_fact" for v in self.bible.diff(before, after)))

    def test_save_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bible.json"
            self.bible.save(path)
            loaded = Bible.load(path)
            self.assertIn("haley", loaded.characters)
            self.assertEqual(loaded.props["compact_mirror"].held_by, "francine")


class EpistemicTests(unittest.TestCase):
    def test_known_fact_presented_as_new_is_flagged(self):
        ledger = Ledger()
        ledger.learn("rainee", "the car is a sedan")
        violations = ledger.check("rainee", "Rainee learned for the first time that the car was a sedan.")
        self.assertTrue(any(v.rule == "known_information_forgetting" for v in violations))

    def test_new_information_is_not_flagged(self):
        ledger = Ledger()
        ledger.learn("rainee", "francine is a nurse")
        violations = ledger.check("rainee", "Rainee learned that the house had a basement.")
        self.assertEqual(violations, [])

    def test_prompt_block(self):
        ledger = Ledger()
        ledger.learn("haley", "the mirror is broken")
        self.assertIn("already knows", ledger.prompt_block("haley"))


if __name__ == "__main__":
    unittest.main()
