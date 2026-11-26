"""
Unit tests for Milestone M-SG2: Causal Dependency DAG & Beat Sequencer.
Verifies topological sort, cycle detection, causal dependency gating,
precondition evaluation, and end-to-end beat sequencing.
"""

import sys
import unittest
from pathlib import Path

# Ensure root directory is on PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from story_graph import (
    BeatNode,
    BeatSequencer,
    CausalDAG,
    CycleError,
    LocationPrecondition,
    PortalState,
    Posture,
)
from story_graph.scenarios.spring_breakup import build_spring_breakup_world
from story_graph.scenarios.spring_breakup_dag import build_spring_breakup_dag


class TestStoryGraphDAG(unittest.TestCase):

    def test_dag_topological_sort(self):
        dag = build_spring_breakup_dag()
        order = dag.validate()
        self.assertEqual(len(order), 10)
        # Verify essential causal ordering
        self.assertLess(order.index("beat_01_francine_kitchen_briefing"), order.index("beat_02_haley_toot_quip"))
        self.assertLess(order.index("beat_03_rainee_vanity_glamour"), order.index("beat_04_rainee_gut_coup"))
        self.assertLess(order.index("beat_04_rainee_gut_coup"), order.index("beat_05_rainee_bathroom_sprint"))
        self.assertLess(order.index("beat_07_first_detonation"), order.index("beat_08_haley_scent_discovery"))
        self.assertLess(order.index("beat_08_haley_scent_discovery"), order.index("beat_09_monster_blast_and_exit"))
        self.assertLess(order.index("beat_09_monster_blast_and_exit"), order.index("beat_10_interrupted_exit"))

    def test_cycle_detection(self):
        dag = CausalDAG()
        dag.add_beat(BeatNode("b1", "Beat 1", "s1", "Desc", dependencies=["b2"]))
        dag.add_beat(BeatNode("b2", "Beat 2", "s1", "Desc", dependencies=["b1"]))
        with self.assertRaises(CycleError):
            dag.validate()

    def test_precondition_and_dependency_blocking(self):
        world = build_spring_breakup_world()
        dag = build_spring_breakup_dag()
        sequencer = BeatSequencer(dag, world)

        # Attempting to fire Beat 5 (Sprint to bathroom) before Beat 4 (Gut coup) must fail
        can_exec, reasons = sequencer.can_execute("beat_05_rainee_bathroom_sprint")
        self.assertFalse(can_exec)
        self.assertTrue(any("Prerequisite beat 'beat_04_rainee_gut_coup' is not completed" in r for r in reasons))

        with self.assertRaises(ValueError):
            sequencer.execute_beat("beat_05_rainee_bathroom_sprint")

    def test_full_scenario_execution(self):
        world = build_spring_breakup_world()
        dag = build_spring_breakup_dag()
        sequencer = BeatSequencer(dag, world)

        # Initial eligible beats should be root nodes: Beat 1 and Beat 3
        eligible_initial = [b.id for b in sequencer.get_eligible_beats()]
        self.assertIn("beat_01_francine_kitchen_briefing", eligible_initial)
        self.assertIn("beat_03_rainee_vanity_glamour", eligible_initial)

        # Step 1: Execute Beat 1 (Francine Kitchen Briefing)
        rec1 = sequencer.execute_beat("beat_01_francine_kitchen_briefing")
        self.assertEqual(rec1["beat_id"], "beat_01_francine_kitchen_briefing")
        self.assertEqual(len(rec1["raw_dialogue"]), 3)

        # Step 2: Execute Beat 2 (Haley Toot Quip & Staircase Transit)
        rec2 = sequencer.execute_beat("beat_02_haley_toot_quip")
        self.assertEqual(world.characters["haley"].location, "staircase")
        self.assertEqual(world.characters["haley"].posture, Posture.STANDING)

        # Step 3: Execute Beat 3 (Rainee Brazilian Vanity Routine)
        sequencer.execute_beat("beat_03_rainee_vanity_glamour")
        self.assertEqual(world.characters["rainee"].location, "master_bedroom")

        # Step 4: Execute Beat 4 (Rainee Sudden Gut Coup)
        sequencer.execute_beat("beat_04_rainee_gut_coup")
        self.assertEqual(world.characters["rainee"].somatic["gut_state"], "acute_colic_spasm")
        self.assertFalse(world.characters["rainee"].holds("lipstick"))

        # Step 5: Execute Beat 5 (Rainee Bathroom Sprint & Deadbolt Lock)
        sequencer.execute_beat("beat_05_rainee_bathroom_sprint")
        self.assertEqual(world.characters["rainee"].location, "master_bathroom")
        self.assertEqual(world.portals["master_bathroom_door"].state, PortalState.LOCKED)

        # Step 6: Execute Beat 6 (Strained Shouting Across HVAC)
        sequencer.execute_beat("beat_06_strained_shouting")

        # Step 7: Execute Beat 7 (First Blast & Burrito Blame)
        sequencer.execute_beat("beat_07_first_detonation")
        self.assertEqual(world.characters["rainee"].somatic["gut_state"], "evacuating")

        # Step 8: Execute Beat 8 (Haley Scent Discovery Outside Door)
        sequencer.execute_beat("beat_08_haley_scent_discovery")
        self.assertEqual(world.characters["haley"].location, "master_bedroom")

        # Step 9: Execute Beat 9 (Monster Farce Blast & Haley Retreat)
        sequencer.execute_beat("beat_09_monster_blast_and_exit")
        self.assertEqual(world.characters["haley"].location, "staircase")

        # Step 10: Execute Beat 10 (Rainee Recovery & Interrupted Exit)
        sequencer.execute_beat("beat_10_interrupted_exit")
        self.assertEqual(world.characters["rainee"].posture, Posture.KNEELING)

        # Verify completion
        self.assertTrue(sequencer.is_finished())
        self.assertEqual(len(sequencer.execution_log), 10)

        # Verify all dialogue lines across beats are frozen
        total_dialogue_lines = 0
        for record in sequencer.execution_log:
            for d in record["raw_dialogue"]:
                self.assertTrue(d["frozen"])
                total_dialogue_lines += 1

        self.assertEqual(total_dialogue_lines, 17)


if __name__ == "__main__":
    unittest.main()
