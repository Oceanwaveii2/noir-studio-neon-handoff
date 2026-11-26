"""
Unit Tests for Mandatory Joke & Somatic Gag Injector.
Milestone M-PE4: Mandatory Joke & Somatic Gag Injector.
"""

import json
import unittest
from pathlib import Path

from prose_engine.gag_injector import (
    CANONICAL_GAGS,
    BeatGagPackage,
    GagAuditReport,
    GagComplianceError,
    GagDefinition,
    InjectedGag,
    MandatoryGagInjector,
)


class TestMandatoryGagInjector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.injector = MandatoryGagInjector()
        cls.deep_scan_manifest_path = (
            cls.repo_root / "work" / "americandad" / "spring_breakup_deep_scan_manifest.json"
        )
        cls.gag_manifest_output_path = (
            cls.repo_root / "work" / "americandad" / "spring_breakup_gag_enriched_manifest.json"
        )

    def test_canonical_gag_matrix_complete(self):
        """Verifies all 6 mandatory farce mechanics are registered with complete metadata."""
        expected_gags = {
            "acoustic_tile_amplification",
            "bowl_water_vibration",
            "towel_muffle_failure",
            "outboard_motor_shudder",
            "dead_flower_shop_clash",
            "seat_lift_recoil",
        }
        self.assertEqual(set(CANONICAL_GAGS.keys()), expected_gags)

        for gag_id, gag in CANONICAL_GAGS.items():
            self.assertIsInstance(gag, GagDefinition)
            self.assertTrue(len(gag.name) > 0)
            self.assertTrue(len(gag.author) > 0)
            self.assertTrue(len(gag.source_book) > 0)
            self.assertTrue(len(gag.mechanic_description) > 30)
            self.assertGreaterEqual(len(gag.verification_patterns), 2)
            self.assertGreaterEqual(len(gag.prose_templates), 1)
            self.assertGreaterEqual(len(gag.required_keywords), 2)

    def test_get_gags_for_farce_beat(self):
        """Beat 7 (first detonation) must receive >= 3 signature farce mechanics."""
        gags = self.injector.get_gags_for_beat("beat_07_first_detonation", "farce_fart")
        self.assertGreaterEqual(len(gags), 3)

        gag_ids = [g.gag_id for g in gags]
        self.assertIn("acoustic_tile_amplification", gag_ids)
        self.assertIn("bowl_water_vibration", gag_ids)
        self.assertIn("towel_muffle_failure", gag_ids)

        for g in gags:
            self.assertIsInstance(g, InjectedGag)
            self.assertTrue(len(g.prose_payload) > 20)
            self.assertGreaterEqual(len(g.verification_patterns), 2)

    def test_audit_scene_passes_with_three_or_more_gags(self):
        """Auditor must pass scenes containing >= 3 verified mechanics."""
        compliant_scene = (
            "Rainee gripped the porcelain sink as the glazed tiles acted like an acoustic amphitheater, "
            "echoing the concussive sound throughout the room. Beneath her, the standing bowl water shivered "
            "into tight concentric ripples like an over-pressurized boiler threat. She grabbed a peach guest towel "
            "to muffle the epicenter, but the blast violently blew past the terrycloth with a screeching kazoo buzz. "
            "A subterranean shudder shook her lower ribs like an old two-stroke outboard motor pull-started in wet cement."
        )

        report = self.injector.audit_scene(compliant_scene, minimum_gags=3)
        self.assertIsInstance(report, GagAuditReport)
        self.assertTrue(report.passed_threshold)
        self.assertGreaterEqual(report.detected_count, 3)
        self.assertIn("acoustic_tile_amplification", report.detected_gags)
        self.assertIn("bowl_water_vibration", report.detected_gags)
        self.assertIn("towel_muffle_failure", report.detected_gags)
        self.assertIn("outboard_motor_shudder", report.detected_gags)

    def test_audit_scene_fails_when_below_threshold(self):
        """Auditor must fail scenes containing fewer than the minimum required gags."""
        insufficient_scene = (
            "She sat on the toilet and farted loudly. It made a PFFFT sound and she felt relieved."
        )

        report = self.injector.audit_scene(insufficient_scene, minimum_gags=3)
        self.assertFalse(report.passed_threshold)
        self.assertLess(report.detected_count, 3)

    def test_assert_gag_compliance_raises_error(self):
        """assert_gag_compliance must raise GagComplianceError when minimum gags are not met."""
        insufficient_scene = "Just a generic bathroom scene with no specific book mechanics."
        with self.assertRaises(GagComplianceError):
            self.injector.assert_gag_compliance(insufficient_scene, minimum_gags=3)

    def test_enrich_manifest_end_to_end(self):
        """End-to-end: Enriching deep scan manifest produces valid gag packages across farce beats."""
        self.assertTrue(self.deep_scan_manifest_path.exists())

        res = self.injector.enrich_manifest(
            deep_scan_manifest_path=self.deep_scan_manifest_path,
            output_path=self.gag_manifest_output_path,
        )

        self.assertEqual(res["beat_count"], 10)
        self.assertGreaterEqual(res["total_farce_beats"], 4)
        self.assertGreaterEqual(res["total_gags_injected"], 8)
        self.assertTrue(self.gag_manifest_output_path.exists())

        # Verify Beat 7 package
        b7 = res["beats"]["beat_07_first_detonation"]["gag_package"]
        self.assertTrue(b7["is_farce_beat"])
        self.assertGreaterEqual(b7["total_gags"], 3)
        g_ids = [g["gag_id"] for g in b7["assigned_gags"]]
        self.assertIn("acoustic_tile_amplification", g_ids)
        self.assertIn("bowl_water_vibration", g_ids)
        self.assertIn("towel_muffle_failure", g_ids)

        # Verify Beat 8 package (Dead flower shop)
        b8 = res["beats"]["beat_08_haley_scent_discovery"]["gag_package"]
        self.assertTrue(b8["is_farce_beat"])
        g8_ids = [g["gag_id"] for g in b8["assigned_gags"]]
        self.assertIn("dead_flower_shop_clash", g8_ids)


if __name__ == "__main__":
    unittest.main()
