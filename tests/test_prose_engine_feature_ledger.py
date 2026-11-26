"""
Unit tests for Milestone M-PE1: Aesthetic & Element Feature Ledger Extractor.
Verifies semantic pre-pass feature extraction, anatomical recognition,
somatic farce detection, and vector query generation.
"""

import json
import sys
import unittest
from pathlib import Path

# Ensure root directory is on PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prose_engine.prepass import (
    AestheticFeatureLedger,
    FeatureCategory,
)


class TestProseEngineFeatureLedger(unittest.TestCase):

    def setUp(self):
        self.ledger = AestheticFeatureLedger()
        self.manifest_path = ROOT / "work" / "americandad" / "spring_breakup_beat_manifest.json"
        self.manifest_data = json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def test_extract_bubble_butt_and_brazilian_curves(self):
        # Beat 3: Rainee Brazilian Vanity Routine
        packets = self.manifest_data["packets"]
        beat_3 = next(p for p in packets if p["beat_id"] == "beat_03_rainee_vanity_glamour")

        profile = self.ledger.extract_from_packet(beat_3)
        self.assertEqual(profile.beat_id, "beat_03_rainee_vanity_glamour")
        self.assertEqual(profile.dominant_routing, "brazilian_sensual")

        feature_ids = [f.id for f in profile.features]
        self.assertIn("bubble_butt", feature_ids)
        self.assertIn("guitar_curves", feature_ids)

        # Check sensory anchors and vector query paths
        self.assertTrue(any("sun-warmed silk" in q for q in profile.vector_query_paths))
        self.assertTrue(any("Copacabana" in q for q in profile.vector_query_paths))
        self.assertTrue(any("Brazilian acoustic guitar" in a for a in profile.mandatory_physical_anchors))

    def test_extract_dead_flower_shop_and_porcelain_acoustics(self):
        # Beat 8: Haley Scent Discovery
        packets = self.manifest_data["packets"]
        beat_8 = next(p for p in packets if p["beat_id"] == "beat_08_haley_scent_discovery")

        profile = self.ledger.extract_from_packet(beat_8)
        self.assertEqual(profile.beat_id, "beat_08_haley_scent_discovery")
        self.assertEqual(profile.dominant_routing, "farce_fart")

        feature_ids = [f.id for f in profile.features]
        self.assertIn("dead_flower_shop_clash", feature_ids)
        self.assertIn("porcelain_acoustics", feature_ids)

        # Check vector queries contain Franklin and Roach
        queries_str = " ".join(profile.vector_query_paths)
        self.assertIn("Benjamin Franklin", queries_str)
        self.assertIn("Mary Roach", queries_str)
        self.assertIn("flower shop died", queries_str)

    def test_extract_suburban_dinner_authority(self):
        # Beat 1: Francine Kitchen Departure Briefing
        packets = self.manifest_data["packets"]
        beat_1 = next(p for p in packets if p["beat_id"] == "beat_01_francine_kitchen_briefing")

        profile = self.ledger.extract_from_packet(beat_1)
        self.assertEqual(profile.beat_id, "beat_01_francine_kitchen_briefing")
        self.assertEqual(profile.dominant_routing, "domestic_farce")

        feature_ids = [f.id for f in profile.features]
        self.assertIn("suburban_dinner_authority", feature_ids)

        queries_str = " ".join(profile.vector_query_paths)
        self.assertIn("P.G. Wodehouse", queries_str)
        self.assertIn("casserole", queries_str)

    def test_extract_cleft_chin_morph(self):
        # Mock beat where Rainee transforms and grows a butt cleft chin
        mock_packet = {
            "beat_id": "beat_mock_peter_morph",
            "scene_id": "scene_mock",
            "description": "Rainee's jaw ripples into a heavy butt chin with a deep cleft chin like Peter Griffin.",
            "aesthetic_tags": ["butt_chin", "cleft_chin", "voluptuous_curves"],
            "raw_dialogue": [
                {"speaker": "RAINEE", "text": "Felt like I swallowed a weather balloon."}
            ]
        }

        profile = self.ledger.extract_from_packet(mock_packet)
        self.assertEqual(profile.dominant_routing, "body_morph")

        feature_ids = [f.id for f in profile.features]
        self.assertIn("cleft_chin", feature_ids)

        queries_str = " ".join(profile.vector_query_paths)
        self.assertIn("double-cleft chin", queries_str)

    def test_full_manifest_extraction_and_ledger_export(self):
        profiles = self.ledger.extract_from_manifest(self.manifest_data)
        self.assertEqual(len(profiles), 10)

        # Export test ledger JSON
        out_path = ROOT / "work" / "americandad" / "spring_breakup_aesthetic_ledger.json"
        json_str = self.ledger.export_ledger_json(profiles, out_path)

        self.assertTrue(out_path.exists())
        exported_data = json.loads(json_str)
        self.assertEqual(exported_data["beat_count"], 10)
        self.assertEqual(len(exported_data["profiles"]), 10)

        # Verify every beat has non-empty vector queries
        for b_id, prof_data in exported_data["profiles"].items():
            self.assertTrue(len(prof_data["vector_query_paths"]) > 0, f"Beat '{b_id}' has 0 vector queries.")
            self.assertTrue(len(prof_data["mandatory_physical_anchors"]) > 0, f"Beat '{b_id}' has 0 mandatory anchors.")


if __name__ == "__main__":
    unittest.main()
