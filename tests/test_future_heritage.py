"""
Future Heritage regression tests.

The S18 Hot Scoomp arc is planned canon. It must be recorded, and it must not leak into
the current S04E16 story, where Haley is human, dormant, and dating Jeff.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prose_engine.voice.world_state import WorldState
from story_graph.future_heritage import (
    HOT_SCOOMP_S18,
    HOT_SCOOMP_VARIANTS,
    FUTURE_HERITAGE,
    get_future_heritage,
    get_hot_scoomp_variant,
)
from story_graph.ontology import OntologyGraph


class TestFutureHeritage(unittest.TestCase):
    def test_s18_record_is_present_and_planned(self):
        self.assertEqual(HOT_SCOOMP_S18.first_active_season, "S18")
        self.assertEqual(HOT_SCOOMP_S18.status, "PLANNED_NOT_ACTIVE")
        self.assertEqual(HOT_SCOOMP_S18.canon_variant, "afm_canon")
        self.assertEqual(len(HOT_SCOOMP_S18.beats), 7)
        self.assertIn(HOT_SCOOMP_S18.heritage_id, FUTURE_HERITAGE)
        self.assertIs(get_future_heritage(HOT_SCOOMP_S18.heritage_id), HOT_SCOOMP_S18)

        blob = " ".join(
            [HOT_SCOOMP_S18.premise]
            + [beat.summary for beat in HOT_SCOOMP_S18.beats]
            + list(HOT_SCOOMP_S18.canon_rules)
        ).lower()
        for keyword in ("cia", "relic", "fox", "rainee", "jeff", "avatar", "cult"):
            self.assertIn(keyword, blob)

    def test_hot_scoomp_variant_breakdown(self):
        self.assertEqual(len(HOT_SCOOMP_VARIANTS), 5)
        canon = [v for v in HOT_SCOOMP_VARIANTS.values() if v.status == "AFM_CANON"]
        self.assertEqual(len(canon), 1)

        afm = get_hot_scoomp_variant("afm_canon")
        self.assertIn("cia", afm.cia_role.lower())
        self.assertIn("rainee", afm.cia_role.lower())
        self.assertIn("booty cult", afm.haley_role.lower())
        self.assertIn("husband", afm.jeff_status.lower())
        self.assertIn("holly graham", afm.jeff_status.lower())
        self.assertIn("jess", afm.jeff_status.lower())
        self.assertIn("brazil", afm.jeff_tag.lower())
        self.assertIn("robbed", afm.jeff_tag.lower())

        source = get_hot_scoomp_variant("source_show_2021")
        self.assertIn("none", source.cia_role.lower())

        future = get_hot_scoomp_variant("s18_future")
        self.assertEqual(future.status, "FUTURE_S18")
        self.assertIn("butt relic", future.cult.lower())
        self.assertIn("husband", future.jeff_status.lower())

    def test_jeff_accumulative_timeline_and_afm_rules(self):
        afm = get_hot_scoomp_variant("afm_canon")
        future = get_hot_scoomp_variant("s18_future")
        cheeks = get_hot_scoomp_variant("transformation_cheeks")

        self.assertIn("spring break", afm.jeff_status.lower())
        self.assertIn("dates jeff in spring break", afm.notes.lower())
        self.assertIn("husband", afm.jeff_status.lower())
        self.assertIn("repulsed", afm.jeff_status.lower())
        self.assertIn("repulsed", future.jeff_status.lower())
        self.assertIn("husband", cheeks.jeff_status.lower())

        rules = " ".join(HOT_SCOOMP_S18.canon_rules).lower()
        self.assertIn("boyfriend jeff", rules)
        self.assertIn("husband", rules)
        self.assertIn("noir", rules)
        self.assertIn("cannot have biological sons", rules)
        self.assertIn("jess", rules)
        self.assertIn("brazil", rules)

    def test_current_story_does_not_apply_s18(self):
        onto = OntologyGraph.create_canonical_foxy_mo2()
        self.assertTrue(onto.future_heritage)
        self.assertEqual(onto.future_heritage[0]["heritage_id"], HOT_SCOOMP_S18.heritage_id)

        summary = " ".join(onto.get_summary_invariants()).lower()
        self.assertNotIn("s18", summary)
        self.assertNotIn("butt relic", summary)
        self.assertNotIn("fox heritage awakens", summary)

        haley_species = onto.character_species["haley"]
        trait = onto.species_registry[haley_species]
        self.assertFalse(trait.can_self_morph)
        self.assertFalse(onto.character_morph_capabilities["haley"]["can_self_morph"])

    def test_current_world_state_has_no_future_heritage(self):
        world = WorldState.load(ROOT / "books" / "world_state.json")
        blob = " ".join(world.rules + [str(item.get("why", "")) for item in world.banned]).lower()
        self.assertNotIn("s18", blob)
        self.assertNotIn("butt relic", blob)
        self.assertNotIn("fox heritage awakens", blob)

    def test_guard_names_the_current_story(self):
        guard = HOT_SCOOMP_S18.current_story_guard.lower()
        self.assertIn("s04e16", guard)
        self.assertIn("not", guard)


if __name__ == "__main__":
    unittest.main()
