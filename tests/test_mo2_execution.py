import unittest

from story_graph.beat_claims import check_claims
from story_graph.models import Transaction
from story_graph.scenarios.foxy_mo2 import build_foxy_mo2_world, run_foxy_mo2
from story_graph.scenarios.foxy_mo2_dag import build_foxy_mo2_dag
from story_graph.transaction_audit import inspect_transactions


class MO2ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packets = run_foxy_mo2()

    def test_full_source_sequence_preserves_dialogue_and_runs_distinct_stages(self):
        dag = build_foxy_mo2_dag()
        self.assertEqual(inspect_transactions(dag, build_foxy_mo2_world()), [])
        self.assertEqual(len(self.packets), 20)
        self.assertEqual([p.beat_id for p in self.packets], list(dag.nodes))
        self.assertEqual([p.raw_dialogue for p in self.packets], [b.raw_dialogue for b in dag.nodes.values()])
        self.assertTrue(all(a.tick < b.tick for a, b in zip(self.packets, self.packets[1:])))
        self.assertEqual(self.packets[4].continuity_context["props"]["toilet"]["seat_units"], 2)
        self.assertEqual(self.packets[4].spatial_context["locations"]["master_bathroom"]
                         ["connected_portals"]["master_bathroom_door"], "locked")
        self.assertEqual(self.packets[9].spatial_context["locations"]["master_bedroom"]
                         ["connected_portals"]["master_bathroom_door"], "open")
        self.assertEqual(self.packets[11].continuity_context["actors"]["haley"], "behind_sofa")
        self.assertEqual(self.packets[-1].continuity_context["actors"]["college_mob"], "living_room")
        self.assertEqual(self.packets[-1].continuity_context["props"]["blue_shopping_cart"]["location"],
                         "held:roger")

    def test_early_late_and_cross_character_claims_use_recorded_world(self):
        early, after = self.packets[3], self.packets[7]
        clean = [
            {"kind": "knows", "subject": "rainee", "value": "burrito_suspected_cause"},
            {"kind": "location", "subject": "haley", "value": "staircase"},
            {"kind": "tick", "subject": early.beat_id, "value": early.tick},
            {"kind": "prop_form", "subject": "toilet", "value": "standard_porcelain"},
        ]
        self.assertEqual(check_claims(early, clean, snapshot=early.world_snapshot_sha256), [])
        wrong = [
            {"kind": "knows", "subject": "haley", "value": "burrito_suspected_cause"},
            {"kind": "location", "subject": "haley", "value": "master_bathroom"},
            {"kind": "tick", "subject": early.beat_id, "value": after.tick},
            {"kind": "prop_location", "subject": "megaphone", "value": "held:roger"},
            {"kind": "available_form", "subject": "rainee", "value": "peter_griffin_celestial_variant"},
            {"kind": "available_form", "subject": "haley", "value": "awakened_haley_fox"},
            {"kind": "available_form", "subject": "stella", "value": "big_tiddy_steve_stella"},
        ]
        self.assertEqual(len(check_claims(early, wrong, snapshot=early.world_snapshot_sha256)), len(wrong))
        self.assertEqual(check_claims(after, wrong[:1], snapshot=after.world_snapshot_sha256), [])
        peter = self.packets[12]
        identity = {"kind": "active_form", "subject": "rainee", "value": "peter_griffin_celestial_variant"}
        self.assertEqual(check_claims(peter, [identity], snapshot=peter.world_snapshot_sha256), [])
        identity["subject"] = "francine"
        self.assertEqual(len(check_claims(peter, [identity], snapshot=peter.world_snapshot_sha256)), 1)
        with self.assertRaisesRegex(ValueError, "snapshot"):
            check_claims(after, clean, snapshot=early.world_snapshot_sha256)

    def test_early_morph_and_physical_shortcuts_are_rejected(self):
        world = build_foxy_mo2_world()
        self.assertFalse(world.execute(Transaction("morph_self", "rainee", "rainee",
                                                  {"avatar_id": "peter_griffin_celestial_variant"}),
                                       beat_id="beat_03_rainee_vanity_glamour").success)
        self.assertFalse(world.execute(Transaction("morph_self", "stella", "stella",
                                                  {"avatar_id": "big_tiddy_steve_stella"})).success)
        self.assertFalse(world.execute(Transaction("move", "francine", "master_bathroom")).success)
        world.characters["rainee"].location = "master_bathroom"
        self.assertFalse(world.execute(Transaction("seat_claim", "rainee", "toilet",
                                                  {"is_custom_enlarged": True})).success)
        self.assertFalse(world.execute(Transaction("move", "rainee", "master_bedroom")).success)
