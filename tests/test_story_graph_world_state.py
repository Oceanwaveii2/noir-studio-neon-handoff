"""
Unit tests for Milestone M-SG1: World State Ledger & Fluent Tracker.
Verifies spatial topology, legal/illegal state transactions, somatic fluents,
and sensory propagation using standard library unittest.
"""

import sys
import unittest
from pathlib import Path

# Ensure root directory is on PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from story_graph import (
    PortalState,
    Posture,
    StoryWorldState,
    Transaction,
)
from story_graph.models import CharacterState, Location, Portal, PropState
from story_graph.scenarios.spring_breakup import build_spring_breakup_world


class TestStoryGraphWorldState(unittest.TestCase):

    def test_initial_world_state(self):
        world = build_spring_breakup_world()
        self.assertEqual(len(world.locations), 6)
        self.assertEqual(len(world.portals), 6)
        self.assertEqual(len(world.characters), 3)

        # Check Rainee's initial Brazilian physique fluents
        rainee = world.characters["rainee"]
        self.assertEqual(rainee.location, "master_bedroom")
        self.assertEqual(rainee.posture, Posture.SEATED)
        self.assertEqual(rainee.physique["hips"], "voluptuous_bubble_butt")
        self.assertTrue(rainee.holds("lipstick"))

    def test_legal_drop_and_move(self):
        world = build_spring_breakup_world()

        # 1. Rainee drops lipstick on bedroom vanity
        res_drop = world.execute(Transaction(
            action="drop",
            actor="rainee",
            target="lipstick"
        ))
        self.assertTrue(res_drop.success)
        self.assertFalse(world.characters["rainee"].holds("lipstick"))
        self.assertIn("lipstick", world.locations["master_bedroom"].props)

        # 2. Rainee runs into bathroom through open door
        res_move = world.execute(Transaction(
            action="move",
            actor="rainee",
            target="master_bathroom"
        ))
        self.assertTrue(res_move.success)
        self.assertEqual(world.characters["rainee"].location, "master_bathroom")

    def test_lock_and_illegal_traversal_blocking(self):
        world = build_spring_breakup_world()

        # Move Rainee into bathroom
        world.execute(Transaction(action="move", actor="rainee", target="master_bathroom"))

        # Rainee locks the deadbolt from inside the bathroom
        res_lock = world.execute(Transaction(
            action="lock",
            actor="rainee",
            target="master_bathroom_door"
        ))
        self.assertTrue(res_lock.success)
        self.assertEqual(world.portals["master_bathroom_door"].state, PortalState.LOCKED)

        # Haley moves from living room -> staircase -> upstairs hallway -> master bedroom
        world.execute(Transaction(action="move", actor="haley", target="staircase"))
        world.execute(Transaction(action="move", actor="haley", target="upstairs_hallway"))
        world.execute(Transaction(action="move", actor="haley", target="master_bedroom"))
        self.assertEqual(world.characters["haley"].location, "master_bedroom")

        # INVARIANT CHECK: Haley tries to enter master_bathroom while door is locked
        res_illegal_move = world.execute(Transaction(
            action="move",
            actor="haley",
            target="master_bathroom"
        ))
        self.assertFalse(res_illegal_move.success)
        self.assertIn("portal is locked", res_illegal_move.reason.lower())
        # Ensure Haley is still in master_bedroom, NOT master_bathroom
        self.assertEqual(world.characters["haley"].location, "master_bedroom")

    def test_somatic_fluent_tracking(self):
        world = build_spring_breakup_world()

        # Acute colic onset
        res_somatic = world.execute(Transaction(
            action="somatic_update",
            actor="rainee",
            target="rainee",
            params={
                "somatic": {
                    "gut_state": "acute_colic_spasm",
                    "gas_pressure_psi": 18.5,
                    "colic_pain": 9
                }
            }
        ))
        self.assertTrue(res_somatic.success)
        rainee = world.characters["rainee"]
        self.assertEqual(rainee.somatic["gut_state"], "acute_colic_spasm")
        self.assertEqual(rainee.somatic["gas_pressure_psi"], 18.5)

    def test_acoustic_and_olfactory_propagation(self):
        world = build_spring_breakup_world()

        # Move Rainee into bathroom and lock door
        world.execute(Transaction(action="move", actor="rainee", target="master_bathroom"))
        world.execute(Transaction(action="lock", actor="rainee", target="master_bathroom_door"))

        # Haley moves to master_bedroom outside the door
        world.execute(Transaction(action="move", actor="haley", target="staircase"))
        world.execute(Transaction(action="move", actor="haley", target="upstairs_hallway"))
        world.execute(Transaction(action="move", actor="haley", target="master_bedroom"))

        # 1. Acoustic Propagation: Francine in Kitchen can be heard by Rainee in Bathroom via HVAC duct
        can_hear, clarity = world.can_hear("rainee", "kitchen")
        self.assertTrue(can_hear)
        self.assertGreater(clarity, 0.0)

        # 2. Olfactory Propagation: Haley in Master Bedroom can smell gas originating in Master Bathroom
        can_smell, intensity = world.can_smell("haley", "master_bathroom")
        self.assertTrue(can_smell)
        self.assertGreater(intensity, 0.5)

    def test_snapshot_and_rollback(self):
        world = build_spring_breakup_world()
        snap = world.snapshot()

        # Mutate state
        world.execute(Transaction(action="move", actor="rainee", target="master_bathroom"))
        self.assertEqual(world.characters["rainee"].location, "master_bathroom")

        # Restore
        restored = StoryWorldState(title=snap["title"])
        restored.tick = snap["tick"]
        for loc_dict in snap["locations"].values():
            restored.add_location(Location(**loc_dict))
        for p_dict in snap["portals"].values():
            p_dict["state"] = PortalState(p_dict["state"])
            restored.add_portal(Portal(**p_dict))
        for c_dict in snap["characters"].values():
            c_dict["posture"] = Posture(c_dict["posture"])
            restored.add_character(CharacterState(**c_dict))
        for pr_dict in snap["props"].values():
            restored.add_prop(PropState(**pr_dict))

        self.assertEqual(restored.characters["rainee"].location, "master_bedroom")

    def test_compile_beat_context(self):
        world = build_spring_breakup_world()
        world.execute(Transaction(action="move", actor="rainee", target="master_bathroom"))
        world.execute(Transaction(action="lock", actor="rainee", target="master_bathroom_door"))

        context = world.compile_beat_context(active_characters=["rainee"])
        self.assertIn("rainee", context["active_characters"])
        self.assertEqual(context["active_characters"]["rainee"]["location"], "master_bathroom")
        self.assertEqual(context["active_characters"]["rainee"]["physique"]["hips"], "voluptuous_bubble_butt")
        self.assertIn("master_bathroom", context["locations"])
        self.assertEqual(context["locations"]["master_bathroom"]["portals"]["master_bathroom_door"], "locked")


if __name__ == "__main__":
    unittest.main()
