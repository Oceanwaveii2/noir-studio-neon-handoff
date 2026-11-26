"""
Unit tests for Milestone M-SG3: Epistemic Knowledge Ledger.
Verifies character knowledge boundaries, acoustic speech propagation,
sensory inference, and dialogue leakage auditing.
"""

import sys
import unittest
from pathlib import Path

# Ensure root directory is on PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from story_graph.scenarios.spring_breakup import build_spring_breakup_world
from story_graph.scenarios.spring_breakup_epistemic import build_spring_breakup_epistemic_ledger


class TestStoryGraphEpistemic(unittest.TestCase):

    def test_initial_knowledge_boundaries(self):
        ledger = build_spring_breakup_epistemic_ledger()

        # Francine knows about Baba and dinners
        self.assertTrue(ledger.knows("francine", "fact_baba_hernia"))
        self.assertTrue(ledger.knows("francine", "fact_preparedness_dinners"))

        # Haley initially does NOT know them
        self.assertFalse(ledger.knows("haley", "fact_baba_hernia"))
        self.assertFalse(ledger.knows("haley", "fact_ancestral_toot_massage"))

        # Nobody knows about Jeff's burrito at start
        self.assertFalse(ledger.knows("rainee", "fact_jeff_burrito_cause"))
        self.assertFalse(ledger.knows("haley", "fact_jeff_burrito_cause"))

    def test_speech_knowledge_propagation(self):
        world = build_spring_breakup_world()
        ledger = build_spring_breakup_epistemic_ledger()

        # Francine in kitchen speaks about Baba's hernia
        overheard = ledger.broadcast_speech(
            speaker_id="francine",
            fact_id="fact_baba_hernia",
            world=world,
            tick=1
        )

        # Haley is in living_room (connected via archway with sound_attenuation=0.9)
        self.assertIn("haley", overheard)
        self.assertTrue(ledger.knows("haley", "fact_baba_hernia"))

    def test_sensory_inference_propagation(self):
        world = build_spring_breakup_world()
        ledger = build_spring_breakup_epistemic_ledger()

        # Rainee is in master_bathroom with door locked
        from story_graph.models import Transaction
        world.execute(Transaction(action="move", actor="rainee", target="master_bathroom"))
        world.execute(Transaction(action="lock", actor="rainee", target="master_bathroom_door"))

        # Haley arrives in master_bedroom outside the door
        world.execute(Transaction(action="move", actor="haley", target="staircase"))
        world.execute(Transaction(action="move", actor="haley", target="upstairs_hallway"))
        world.execute(Transaction(action="move", actor="haley", target="master_bedroom"))

        # Haley infers Rainee's bathroom distress from scent draft rolling under the door
        inferred = ledger.infer_from_sensory(
            sniffer_id="haley",
            fact_id="fact_rainee_bathroom_distress",
            source_loc="master_bathroom",
            world=world,
            tick=8
        )
        self.assertTrue(inferred)
        self.assertTrue(ledger.knows("haley", "fact_rainee_bathroom_distress"))

    def test_dialogue_leakage_detection(self):
        ledger = build_spring_breakup_epistemic_ledger()

        # CASE 1: LEAK DETECTED
        # Haley tries to say "Did Jeff's burrito cause this?" in Beat 1 before she knows it
        illegal_dialogue = "Hey Mom, did you eat Jeff's burrito last night?"
        leaks = ledger.audit_text_for_leaks("haley", illegal_dialogue, tick=1)
        self.assertEqual(len(leaks), 1)
        self.assertEqual(leaks[0][0], "fact_jeff_burrito_cause")
        self.assertEqual(leaks[0][1].lower(), "burrito")

        # CASE 2: LEGAL DIALOGUE (No leaks)
        # Francine talks about lasagna (which she knows)
        legal_dialogue = "Okay troops, three nights of lasagna!"
        leaks_francine = ledger.audit_text_for_leaks("francine", legal_dialogue, tick=1)
        self.assertEqual(len(leaks_francine), 0)

        # CASE 3: KNOWLEDGE ACQUISITION CLEARS LEAK
        # In Beat 9, Haley acquires the burrito fact via deduction
        ledger.grant_knowledge("haley", "fact_jeff_burrito_cause", source_type="sensory_inference", tick=9)
        self.assertTrue(ledger.knows("haley", "fact_jeff_burrito_cause"))

        # Now Haley saying "That's definitely Jeff's burrito" is 100% legal
        leaks_haley_beat9 = ledger.audit_text_for_leaks("haley", "Yeah, that's definitely Jeff's burrito.", tick=9)
        self.assertEqual(len(leaks_haley_beat9), 0)

    def test_snapshot_and_rollback(self):
        ledger = build_spring_breakup_epistemic_ledger()
        snap = ledger.snapshot()

        # Grant knowledge
        ledger.grant_knowledge("haley", "fact_jeff_burrito_cause", source_type="speech", tick=5)
        self.assertTrue(ledger.knows("haley", "fact_jeff_burrito_cause"))

        # Restore
        restored = build_spring_breakup_epistemic_ledger()
        restored.restore(snap)
        self.assertFalse(restored.knows("haley", "fact_jeff_burrito_cause"))


if __name__ == "__main__":
    unittest.main()
