"""Appearance canon contracts."""

import json
import tempfile
import unittest
from pathlib import Path

from prose_engine.voice.appearance import (
    Appearance,
    AppearanceBible,
    parse_schema,
)

SAMPLE = Appearance(
    entity="rainee",
    image="images/rainee.png",
    immutable_base_traits=["dark hair", "tail"],
    state_deltas={"pre_transformation": ["dark hair", "tail"], "peter": ["grey dome", "wide jaw"]},
    forbidden_claims=["hair vanished", "tail missing"],
    palette=["crimson", "chrome"],
    silhouette="wide hips, high tail",
)


class AppearanceTests(unittest.TestCase):
    def test_save_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rainee.json"
            SAMPLE.save(path)
            loaded = Appearance.load(path)
            self.assertEqual(loaded.entity, "rainee")
            self.assertEqual(loaded.state_deltas["peter"], ["grey dome", "wide jaw"])

    def test_forbidden_claim_flagged(self):
        self.assertTrue(any("hair vanished" in item for item in SAMPLE.check("Her hair vanished in the dome.")))

    def test_immutable_trait_erasure_flagged(self):
        self.assertTrue(SAMPLE.check("The tail was gone by morning."))

    def test_valid_text_passes(self):
        self.assertEqual(SAMPLE.check("The tail thickens and the dark hair stays put."), [])

    def test_prompt_block_lists_canon(self):
        block = SAMPLE.prompt_block()
        self.assertIn("always: dark hair, tail", block)
        self.assertIn("never claim", block)

    def test_parse_schema_from_fenced_reply(self):
        reply = 'Here you go:\n```json\n{"entity":"rainee","immutable_base_traits":["tail"],"forbidden_claims":["tail missing"],"palette":["red"]}\n```'
        appearance = parse_schema(reply, entity="rainee")
        self.assertEqual(appearance.immutable_base_traits, ["tail"])
        self.assertEqual(appearance.palette, ["red"])

    def test_parse_schema_without_json_raises(self):
        with self.assertRaises(ValueError):
            parse_schema("no json here")

    def test_bible_checks_all_entries(self):
        bible = AppearanceBible({"rainee": SAMPLE})
        self.assertTrue(bible.check("Her hair vanished."))
        self.assertIn("APPEARANCE CANON", bible.prompt_block())


if __name__ == "__main__":
    unittest.main()
