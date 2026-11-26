import unittest
from story_graph.dag import BeatNode, CausalDAG
from story_graph.models import CharacterState, Location, Transaction
from story_graph.transaction_audit import inspect_transactions
from story_graph.world_state import StoryWorldState


class TransactionAuditTests(unittest.TestCase):
    def test_empty_somatic_updates_are_reported_and_valid_update_is_clean(self):
        world = StoryWorldState()
        world.add_location(Location("room", "Room"))
        world.add_character(CharacterState("person", "Person", "room"))
        dag = CausalDAG()
        dag.add_beat(BeatNode("beat", "Beat", "scene", "description", transactions=[
            Transaction("somatic_update", "person", "person", {"form": "new"}),
            Transaction("somatic_update", "person", "person", {"somatic": {"form": "new"}}),
        ]))
        issues = inspect_transactions(dag, world)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["transaction"], 0)

    def test_mo2_transformations_really_update_world(self):
        from story_graph.scenarios.foxy_mo2_dag import build_foxy_mo2_dag
        dag = build_foxy_mo2_dag()
        world = StoryWorldState()
        world.add_location(Location("room", "Room"))
        for character in ("rainee", "francine"):
            world.add_character(CharacterState(character, character, "room"))
        for beat_id, character, expected in (
            ("beat_13_peter_griffin_metamorphosis", "rainee", "peter_griffin_celestial_variant"),
            ("beat_14_nurse_pamela_nanite_transfer", "francine", "nurse_pamela_franny_anderson"),
        ):
            tx = next(t for t in dag.nodes[beat_id].transactions if t.action in ("morph_self", "morph_target"))
            self.assertTrue(world.execute(tx).success)
            self.assertEqual(world.characters[character].active_avatar, expected)
