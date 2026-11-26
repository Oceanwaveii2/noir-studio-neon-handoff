"""S6: room reachability, whole-document re-check, per-proposal rollback."""

import unittest

from prose_engine.conditioner import Proposal, apply_proposals_checked
from prose_engine.voice.ledger import BeatPlan, sections
from prose_engine.voice.recheck import document_issues
from prose_engine.voice.spatial import House
from prose_engine.voice.world_state import WorldState


class ReachabilityTests(unittest.TestCase):
    def setUp(self):
        self.house = House.load()

    def test_kitchen_reaches_bathroom_via_stairs(self):
        self.assertTrue(self.house.reachable("Kitchen / dining", "Full bathroom"))

    def test_kitchen_reaches_basement_lounge(self):
        self.assertTrue(self.house.reachable("Kitchen / dining", "Basement lounge"))

    def test_bedroom_reaches_toilet(self):
        self.assertTrue(self.house.reachable("Bedroom 2", "Wide toilet room"))


class TeleportTests(unittest.TestCase):
    def setUp(self):
        self.house = House.load()

    def test_teleport_is_flagged(self):
        chunks = ["INT. KITCHEN — DAY", "Francine looks at the door.", "INT. BATHROOM — CONTINUOUS", "Francine sits."]
        issues = self.house.check_scene(chunks)
        self.assertTrue(any("transition" in issue for issue in issues))

    def test_stairs_move_is_not_a_teleport(self):
        chunks = ["INT. KITCHEN — DAY", "Francine looks at the door."]
        self.assertEqual(self.house.check_scene(chunks), [])


class RecheckTests(unittest.TestCase):
    def test_plan_flags_missing_beat(self):
        text = "INT. SMITH KITCHEN — DAY\n\nFrancine packs.\n\nINT. BATHROOM — CONTINUOUS\n\nRainee sits."
        issues = document_issues(text, plan=BeatPlan.load())
        self.assertTrue(any("ledger" in issue for issue in issues))


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.world = WorldState.load()
        self.text = "Rainee set the tray down. She looked at the door."

    def test_bad_proposal_is_rolled_back(self):
        bad = Proposal(0, 0, len(self.text), self.text, "Dad set the tray down. She looked at the door.",
                       [], True, "ok")
        updated, applied, rollbacks = apply_proposals_checked(self.text, [bad], world=self.world)
        self.assertEqual(applied, 0)
        self.assertTrue(rollbacks)
        self.assertEqual(updated, self.text)

    def test_clean_proposal_applies(self):
        good = Proposal(1, 0, len(self.text), self.text, "Rainee put the tray down. She looked at the door.",
                        [], True, "ok")
        updated, applied, rollbacks = apply_proposals_checked(self.text, [good], world=self.world)
        self.assertEqual(applied, 1)
        self.assertEqual(rollbacks, [])
        self.assertIn("put the tray down", updated)


if __name__ == "__main__":
    unittest.main()
