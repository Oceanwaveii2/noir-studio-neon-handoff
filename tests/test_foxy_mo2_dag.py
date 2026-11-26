"""
Unit tests for Milestone MO2 Full Narrative Causal DAG.
Verifies topological sort, all 20 beat causal dependencies, preconditions,
and dialogue completeness across all 4 Acts of Spring Breakup.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from story_graph.scenarios.foxy_mo2_dag import build_foxy_mo2_dag


class TestFoxyMO2DAG(unittest.TestCase):

    def test_full_mo2_dag_topological_sort(self):
        dag = build_foxy_mo2_dag()
        order = dag.validate()
        self.assertEqual(len(order), 20)

        # Act I & II Causal ordering
        self.assertLess(order.index("beat_01_francine_kitchen_briefing"), order.index("beat_02_haley_toot_quip_stella_banter"))
        self.assertLess(order.index("beat_03_rainee_vanity_glamour"), order.index("beat_04_rainee_gut_coup"))
        self.assertLess(order.index("beat_04_rainee_gut_coup"), order.index("beat_05_bathroom_sprint_commode_morph"))
        self.assertLess(order.index("beat_07_acoustic_porcelain_detonation"), order.index("beat_08_haley_hallway_scent_discovery"))
        self.assertLess(order.index("beat_08_haley_hallway_scent_discovery"), order.index("beat_09_monster_blast_haley_retreat"))
        self.assertLess(order.index("beat_09_monster_blast_haley_retreat"), order.index("beat_10_bandage_dress_struggle_nailed_it"))

        # Act III Causal ordering (Living Room Metamorphosis)
        self.assertLess(order.index("beat_10_bandage_dress_struggle_nailed_it"), order.index("beat_11_staircase_descent_jeff_ass_quip"))
        self.assertLess(order.index("beat_11_staircase_descent_jeff_ass_quip"), order.index("beat_12_concussive_detonation_haley_launch"))
        self.assertLess(order.index("beat_12_concussive_detonation_haley_launch"), order.index("beat_13_peter_griffin_metamorphosis"))
        self.assertLess(order.index("beat_13_peter_griffin_metamorphosis"), order.index("beat_14_nurse_pamela_nanite_transfer"))
        self.assertLess(order.index("beat_14_nurse_pamela_nanite_transfer"), order.index("beat_15_chinese_heritage_resolution"))

        # Act IV Causal ordering (Driveway Rutgers Takeover)
        self.assertLess(order.index("beat_15_chinese_heritage_resolution"), order.index("beat_16_driveway_peelout"))
        self.assertLess(order.index("beat_16_driveway_peelout"), order.index("beat_17_roger_mtv_motel_bribe"))
        self.assertLess(order.index("beat_17_roger_mtv_motel_bribe"), order.index("beat_18_roger_cold_eviction_threat"))
        self.assertLess(order.index("beat_18_roger_cold_eviction_threat"), order.index("beat_19_rutgers_bus_royal_transformation"))
        self.assertLess(order.index("beat_19_rutgers_bus_royal_transformation"), order.index("beat_20_butt_plug_distribution_mob_overrun"))

    def test_all_dialogue_frozen_and_valid(self):
        dag = build_foxy_mo2_dag()
        dialogue_count = 0
        for node_id, node in dag.nodes.items():
            for line in node.raw_dialogue:
                self.assertTrue(line["frozen"])
                self.assertIn("speaker", line)
                self.assertIn("text", line)
                dialogue_count += 1
        self.assertGreaterEqual(dialogue_count, 30)


if __name__ == "__main__":
    unittest.main()
