"""
Unit Tests for 4-Tier Deep Scan Architecture.
Milestone M-PE3: 4-Tier Deep Scan Architecture.
"""

import json
import unittest
from pathlib import Path

from prose_engine.deep_scan import (
    DeepScanEngine,
    DeepScanResult,
    Tier1Match,
    Tier2Dynamic,
    Tier3Cadence,
    Tier4Idiom,
)
from prose_engine.dispatcher.router import DispatchedCorpus


class TestDeepScanEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.engine = DeepScanEngine()
        cls.dispatched_manifest_path = (
            cls.repo_root / "work" / "americandad" / "spring_breakup_dispatched_manifest.json"
        )
        cls.deep_scan_output_path = (
            cls.repo_root / "work" / "americandad" / "spring_breakup_deep_scan_manifest.json"
        )

    def test_scan_beat_multi_author_exit_criterion(self):
        """Exit Criterion: Every beat packet must receive high-affinity matches from >= 3 distinct authors."""
        corpus = DispatchedCorpus(
            beat_id="test_beat_farce",
            scene_id="test_scene",
            policy_name="farce_fart",
            authorized_books=[
                "gulp_adventures_on_the_alimentary_canal_mary_roach",
                "fart_proudly_benjamin_franklin",
                "me_talk_pretty_one_day_david_sedaris",
                "the_body_a_guide_for_occupants_bill_bryson",
                "guards_guards_swamp_dragon_chronicles_terry_pratchett",
            ],
            blocked_books=[
                "valley_of_the_dolls_jacqueline_susann",
                "the_love_machine_jacqueline_susann",
            ],
            vector_queries=[
                "transverse colon trapped gas pressure peristaltic wave violent cramp",
                "acoustic report rattling porcelain tiles",
            ],
            mandatory_physical_anchors=[
                "white knuckles gripping cold porcelain sink",
                "subterranean rumble echoing through tile",
            ],
        )

        res = self.engine.scan_beat(corpus)
        self.assertIsInstance(res, DeepScanResult)
        self.assertGreaterEqual(res.distinct_author_count, 3)
        self.assertGreaterEqual(len(res.distinct_authors), 3)

        # Verify specific authors present
        authors_lower = [a.lower() for a in res.distinct_authors]
        self.assertTrue(
            any("mary roach" in a or "sedaris" in a or "bryson" in a or "pratchett" in a for a in authors_lower)
        )

    def test_scan_beat_zero_blocked_contamination(self):
        """Zero contamination test: Blocked books and authors must be 100% purged from all matches."""
        corpus = DispatchedCorpus(
            beat_id="test_beat_brazilian",
            scene_id="test_scene",
            policy_name="brazilian_sensual",
            authorized_books=[
                "brazilian_tales_isaac_goldberg",
                "iracema_the_honey_lips_jose_de_alencar",
                "lyrics_dance_pop",
            ],
            blocked_books=[
                "valley_of_the_dolls_jacqueline_susann",
                "the_love_machine_jacqueline_susann",
                "the_world_is_full_of_divorced_women_jackie_collins",
            ],
            vector_queries=[
                "voluptuous bubble butt filling sun-warmed silk with radiant pride",
                "two proud sculpted spheres asserting total territorial dominance",
            ],
            mandatory_physical_anchors=[
                "two proud, sculpted spheres asserting territorial dominance",
            ],
        )

        res = self.engine.scan_beat(corpus)

        # Check blocked authors are listed as purged
        self.assertIn("Jacqueline Susann", res.blocked_authors_purged)
        self.assertIn("Jackie Collins", res.blocked_authors_purged)

        # Check blocked authors NEVER appear in distinct_authors
        for blocked in res.blocked_authors_purged:
            self.assertNotIn(blocked, res.distinct_authors)

        # Check tier 1
        for m in res.tier1_thematic_matches:
            self.assertNotIn("susann", m.author.lower())
            self.assertNotIn("collins", m.author.lower())
            self.assertNotIn("valley_of_the_dolls", m.book_slug)

        # Check tier 4
        for idi in res.tier4_synthesized_idioms:
            self.assertNotEqual(idi.lens, "glamour")
            self.assertNotIn("susann", idi.author.lower())

    def test_tier1_thematic_matches_structure_and_scoring(self):
        """Tier 1 must produce scored thematic matches with valid excerpts and motifs."""
        matches = self.engine.scan_tier1_thematic(
            authorized_books=[
                "gulp_adventures_on_the_alimentary_canal_mary_roach",
                "fart_proudly_benjamin_franklin",
            ],
            vector_queries=["transverse colon trapped gas peristaltic wave cramp"],
            physical_anchors=["gas pressure"],
            top_k=2,
        )

        self.assertGreater(len(matches), 0)
        top = matches[0]
        self.assertIsInstance(top, Tier1Match)
        self.assertGreater(top.relevance_score, 0.0)
        self.assertTrue(len(top.excerpt) > 20)
        self.assertTrue(len(top.motif) > 0)

    def test_tier2_somatic_dynamics_categories(self):
        """Tier 2 must extract somatic and acoustic dynamics across recognized categories."""
        dynamics = self.engine.scan_tier2_dynamics(
            authorized_books=[
                "gulp_adventures_on_the_alimentary_canal_mary_roach",
                "the_bfg_whizzpopping_chronicles_roald_dahl",
            ],
            policy_name="farce_fart",
            top_k=3,
        )

        self.assertGreater(len(dynamics), 0)
        valid_cats = {"onomatopoeia", "visceral_gut", "acoustic_reverberation", "somatic_tension"}
        for d in dynamics:
            self.assertIsInstance(d, Tier2Dynamic)
            self.assertIn(d.category, valid_cats)
            self.assertTrue(len(d.motif_phrase) > 0)
            self.assertTrue(len(d.source_context) > 20)

    def test_tier3_cadence_variance_and_patterns(self):
        """Tier 3 must supply rhythmic cadence models with high sentence length variance (sigma >= 4.0)."""
        cadences = self.engine.scan_tier3_cadence(
            policy_name="farce_fart",
            authorized_books=["breakfast_of_champions_kurt_vonnegut"],
        )

        self.assertGreater(len(cadences), 0)
        for c in cadences:
            self.assertIsInstance(c, Tier3Cadence)
            self.assertGreaterEqual(c.sentence_length_variance, 4.0)
            self.assertTrue(len(c.example_pattern) > 15)

    def test_tier4_idiom_synthesis_volume_and_isolation(self):
        """Tier 4 must synthesize 10-15 idioms while strictly isolating the glamour lens."""
        idioms = self.engine.scan_tier4_idioms(
            policy_name="farce_fart",
            blocked_books=["valley_of_the_dolls_jacqueline_susann"],
            target_count=12,
        )

        self.assertEqual(len(idioms), 12)
        for item in idioms:
            self.assertIsInstance(item, Tier4Idiom)
            self.assertNotEqual(item.lens, "glamour")
            self.assertTrue(len(item.idiom) > 10)

    def test_scan_manifest_end_to_end(self):
        """End-to-end test: Scan all 10 beats of Spring Breakup and verify deep scan manifest."""
        self.assertTrue(self.dispatched_manifest_path.exists())

        manifest_output = self.engine.scan_manifest(
            dispatched_manifest_path=self.dispatched_manifest_path,
            output_path=self.deep_scan_output_path,
        )

        self.assertEqual(manifest_output["beat_count"], 10)
        self.assertTrue(self.deep_scan_output_path.exists())

        # Check Beat 3 (Brazilian Sensual)
        b3 = manifest_output["deep_scans"]["beat_03_rainee_vanity_glamour"]
        self.assertEqual(b3["policy_name"], "brazilian_sensual")
        self.assertGreaterEqual(b3["distinct_author_count"], 3)
        self.assertIn("Jacqueline Susann", b3["blocked_authors_purged"])

        # Check Beat 7 (First Detonation Farce)
        b7 = manifest_output["deep_scans"]["beat_07_first_detonation"]
        self.assertEqual(b7["policy_name"], "farce_fart")
        self.assertGreaterEqual(b7["distinct_author_count"], 3)
        self.assertIn("Jacqueline Susann", b7["blocked_authors_purged"])


if __name__ == "__main__":
    unittest.main()
