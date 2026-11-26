"""
Unit tests for Milestone M-PE2: Segmented Sub-Corpus Dispatcher.
Verifies intelligent section routing, sub-corpus partitioning across 105 books,
soft weighting & genre biasing, and strict hard-block mode.
"""

import json
import sys
import unittest
from pathlib import Path

# Ensure root directory is on PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prose_engine.dispatcher import (
    SubCorpusDispatcher,
)
from prose_engine.prepass import (
    AestheticFeatureLedger,
)


class TestProseEngineDispatcher(unittest.TestCase):

    def setUp(self):
        self.ledger = AestheticFeatureLedger()
        self.dispatcher = SubCorpusDispatcher()
        self.manifest_path = ROOT / "work" / "americandad" / "spring_breakup_beat_manifest.json"
        self.manifest_data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.profiles = self.ledger.extract_from_manifest(self.manifest_data)

    def test_dispatch_brazilian_sensual_soft_weighting_and_bias(self):
        # Beat 3: Rainee Brazilian Vanity Routine
        prof_3 = self.profiles["beat_03_rainee_vanity_glamour"]
        dispatched = self.dispatcher.dispatch(prof_3)

        self.assertEqual(dispatched.policy_name, "brazilian_sensual")

        # 1. Verify Authorized Brazilian & Pop Books have high affinity weights
        weights = dispatched.book_weights
        self.assertGreaterEqual(weights.get("brazilian_tales_isaac_goldberg", 0.0), 1.0)
        self.assertGreaterEqual(weights.get("iracema_the_honey_lips_jose_de_alencar", 0.0), 1.0)
        self.assertGreaterEqual(weights.get("lyrics_dance_pop", 0.0), 1.0)

        # 2. VERIFY SOFT DAMPENING: 1970s Romance Melodrama is de-biased to <= 0.10 weight
        damped_susann = weights.get("valley_of_the_dolls_jacqueline_susann", 0.0)
        damped_collins = weights.get("the_world_is_full_of_divorced_women_jackie_collins", 0.0)
        self.assertLessEqual(damped_susann, 0.10)
        self.assertLessEqual(damped_collins, 0.10)

        # 3. Verify Bias Advantage Ratio >= 10:1 (25x advantage)
        primary_w = weights.get("brazilian_tales_isaac_goldberg", 0.0)
        self.assertGreaterEqual(primary_w / damped_susann, 10.0)

        # 4. Verify candidate ordering: Top-ranked books are 100% primary authorized
        top_books = dispatched.authorized_books[:3]
        for b in top_books:
            self.assertIn(b, ["brazilian_tales_isaac_goldberg", "iracema_the_honey_lips_jose_de_alencar", "lyrics_dance_pop", "gargantua_and_pantagruel_francois_rabelais"])

        # 5. Verify Soft Isolation Audit passes
        ok, violations = self.dispatcher.audit_isolation(dispatched)
        self.assertTrue(ok, f"Violations: {violations}")
        self.assertEqual(len(violations), 0)

    def test_dispatch_strict_hard_block_mode(self):
        """Verifies strict hard-block mode completely removes damped books from authorized pool."""
        prof_3 = self.profiles["beat_03_rainee_vanity_glamour"]
        dispatched_hard = self.dispatcher.dispatch(prof_3, strict_hard_block=True)

        self.assertTrue(dispatched_hard.strict_hard_block)
        self.assertNotIn("valley_of_the_dolls_jacqueline_susann", dispatched_hard.authorized_books)
        self.assertNotIn("the_love_machine_jacqueline_susann", dispatched_hard.authorized_books)
        self.assertNotIn("the_world_is_full_of_divorced_women_jackie_collins", dispatched_hard.authorized_books)

        ok, violations = self.dispatcher.audit_isolation(dispatched_hard)
        self.assertTrue(ok)
        self.assertEqual(len(violations), 0)

    def test_dispatch_farce_fart_soft_weighting(self):
        # Beat 7: First Blast & Jeff Burrito Blame
        prof_7 = self.profiles["beat_07_first_detonation"]
        dispatched = self.dispatcher.dispatch(prof_7)

        self.assertEqual(dispatched.policy_name, "farce_fart")

        # 1. Verify Authorized Modern & Classical Fart Books have dominant weights
        weights = dispatched.book_weights
        self.assertGreaterEqual(weights.get("fart_proudly_benjamin_franklin", 0.0), 1.0)
        self.assertGreaterEqual(weights.get("gulp_adventures_on_the_alimentary_canal_mary_roach", 0.0), 1.0)
        self.assertGreaterEqual(weights.get("the_bfg_whizzpopping_chronicles_roald_dahl", 0.0), 1.0)
        self.assertGreaterEqual(weights.get("me_talk_pretty_one_day_david_sedaris", 0.0), 1.0)

        # 2. VERIFY SOFT DAMPENING on romance melodrama
        self.assertLessEqual(weights.get("valley_of_the_dolls_jacqueline_susann", 0.0), 0.10)

        # 3. Verify Isolation Audit
        ok, violations = self.dispatcher.audit_isolation(dispatched)
        self.assertTrue(ok)
        self.assertEqual(len(violations), 0)

    def test_dispatch_domestic_farce(self):
        # Beat 1: Francine Kitchen Departure Briefing
        prof_1 = self.profiles["beat_01_francine_kitchen_briefing"]
        dispatched = self.dispatcher.dispatch(prof_1)

        self.assertEqual(dispatched.policy_name, "domestic_farce")

        # Verify Authorized Wodehouse and Halpern have high affinity weights
        weights = dispatched.book_weights
        self.assertGreaterEqual(weights.get("right_ho_jeeves_p_g_wodehouse", 0.0), 1.0)
        self.assertGreaterEqual(weights.get("shit_my_dad_says_justin_halpern", 0.0), 1.0)

        # Verify Romance Melodrama is de-biased
        self.assertLessEqual(weights.get("valley_of_the_dolls_jacqueline_susann", 0.0), 0.10)

    def test_full_manifest_dispatch_and_export(self):
        dispatched_map = self.dispatcher.dispatch_manifest(self.profiles)
        self.assertEqual(len(dispatched_map), 10)

        # Verify zero audit violations across all 10 beats
        for b_id, d in dispatched_map.items():
            ok, violations = self.dispatcher.audit_isolation(d)
            self.assertTrue(ok, f"Audit failure in beat '{b_id}': {violations}")
            self.assertTrue(len(d.authorized_books) >= 3, f"Beat '{b_id}' has fewer than 3 authorized books.")

        # Export dispatched manifest JSON
        out_path = ROOT / "work" / "americandad" / "spring_breakup_dispatched_manifest.json"
        data = {
            "version": "1.0",
            "beat_count": len(dispatched_map),
            "dispatches": {b_id: d.to_dict() for b_id, d in dispatched_map.items()},
        }
        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.assertTrue(out_path.exists())


if __name__ == "__main__":
    unittest.main()
