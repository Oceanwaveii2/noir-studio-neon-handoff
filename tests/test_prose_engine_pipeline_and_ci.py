"""
Unit Tests for End-to-End Pipeline & CI Verification Suite.
Milestone M-PE7: End-to-End Integration & CI Verification Suite.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

# Ensure repository root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.ci_hybrid import HybridCIEngine
from tools.run_pipeline import PipelineRunner


class TestPipelineRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = ROOT
        cls.work_dir = cls.repo_root / "work" / "americandad"
        cls.runner = PipelineRunner(out_dir=cls.work_dir, verbose=False)

    def test_run_stage1_story_graph(self):
        """Stage 1 generates valid beat manifest and lean screenplay markdown."""
        manifest_path, script_path = self.runner.run_stage1_story_graph()
        self.assertTrue(manifest_path.exists())
        self.assertTrue(script_path.exists())

        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(data["beat_count"], 10)
        self.assertEqual(len(data["packets"]), 10)

        script_text = script_path.read_text(encoding="utf-8")
        self.assertIn("### INT. KITCHEN - CONTINUOUS", script_text)
        self.assertIn("FRANCINE", script_text)

    def test_run_stage2_feature_ledger(self):
        """Stage 2 extracts aesthetic features and generates profiles for all beats."""
        beat_manifest = self.work_dir / "spring_breakup_beat_manifest.json"
        ledger_path = self.runner.run_stage2_feature_ledger(beat_manifest)
        self.assertTrue(ledger_path.exists())

        data = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(data["beat_count"], 10)
        self.assertIn("beat_03_rainee_vanity_glamour", data["profiles"])

    def test_run_stage3_dispatcher(self):
        """Stage 3 dispatches beats with soft weighting and genre biasing."""
        beat_manifest = self.work_dir / "spring_breakup_beat_manifest.json"
        dispatched_path = self.runner.run_stage3_dispatcher(beat_manifest)
        self.assertTrue(dispatched_path.exists())

        data = json.loads(dispatched_path.read_text(encoding="utf-8"))
        self.assertEqual(data["beat_count"], 10)
        # Verify Beat 3 soft-dampens romance melodrama while primary books dominate
        b3 = data["dispatches"]["beat_03_rainee_vanity_glamour"]
        weights = b3["book_weights"]
        self.assertLessEqual(weights.get("valley_of_the_dolls_jacqueline_susann", 1.0), 0.10)
        self.assertGreaterEqual(weights.get("brazilian_tales_isaac_goldberg", 0.0), 1.0)
        self.assertNotIn("valley_of_the_dolls_jacqueline_susann", b3["authorized_books"][:5])

    def test_run_stage4_deep_scan(self):
        """Stage 4 executes 4-tier deep scan across 105+ books."""
        dispatched_path = self.work_dir / "spring_breakup_dispatched_manifest.json"
        scan_path = self.runner.run_stage4_deep_scan(dispatched_path)
        self.assertTrue(scan_path.exists())

        data = json.loads(scan_path.read_text(encoding="utf-8"))
        scans = data.get("deep_scans", {})
        self.assertEqual(len(scans), 10)
        for b_id, s in scans.items():
            self.assertGreaterEqual(s["distinct_author_count"], 3)

    def test_run_stage5_gag_injector(self):
        """Stage 5 enriches farce beats with canonical farce mechanics."""
        scan_path = self.work_dir / "spring_breakup_deep_scan_manifest.json"
        gag_path = self.runner.run_stage5_gag_injector(scan_path)
        self.assertTrue(gag_path.exists())

        data = json.loads(gag_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(data["total_gags_injected"], 6)

    def test_run_stage6_dialogue_dial(self):
        """Stage 6 dials dialogue per character and enforces 0 drift on Francine (level 0)."""
        gag_path = self.work_dir / "spring_breakup_gag_enriched_manifest.json"
        dialed_path = self.runner.run_stage6_dialogue_dial(
            gag_path, influence_spec="Francine:0 Rainee:50 Haley:20"
        )
        self.assertTrue(dialed_path.exists())

        data = json.loads(dialed_path.read_text(encoding="utf-8"))
        self.assertEqual(data["total_dialed_lines"], 17)

    def test_run_stage7_hybrid_realizer(self):
        """Stage 7 synthesizes hybrid novel passing linter and gag audit."""
        dialed_path = self.work_dir / "spring_breakup_dialed_manifest.json"
        hybrid_path = self.runner.run_stage7_hybrid_realizer(dialed_path)
        self.assertTrue(hybrid_path.exists())

        text = hybrid_path.read_text(encoding="utf-8")
        self.assertIn("### SCENE 1: INT. LING HOUSE — KITCHEN — MORNING", text)
        self.assertIn("### SCENE 2: INT. MASTER BEDROOM — CONTINUOUS", text)
        self.assertIn("### SCENE 3: INT. MASTER BATHROOM — CONTINUOUS", text)

    def test_cli_run_pipeline(self):
        """Verifies python tools/run_pipeline.py CLI runs with exit code 0."""
        cmd = [
            sys.executable,
            "tools/run_pipeline.py",
            "--character-influence",
            "Francine:0 Rainee:50 Haley:20",
        ]
        res = subprocess.run(
            cmd,
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, f"CLI stderr: {res.stderr}")
        self.assertIn("PIPELINE COMPLETE: ALL 7 STAGES PASSED", res.stdout)


class TestHybridCIEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = ROOT
        cls.work_dir = cls.repo_root / "work" / "americandad"
        cls.ci = HybridCIEngine(work_dir=cls.work_dir, verbose=False)

    def test_gate1_story_graph_state(self):
        passed = self.ci.gate_story_graph_state()
        self.assertTrue(passed, f"Gate 1 failed: {self.ci.results.get('story_graph_state')}")

    def test_gate2_segmented_routing(self):
        passed = self.ci.gate_segmented_routing()
        self.assertTrue(passed, f"Gate 2 failed: {self.ci.results.get('segmented_routing')}")

    def test_gate3_deep_scan_coverage(self):
        passed = self.ci.gate_deep_scan_coverage()
        self.assertTrue(passed, f"Gate 3 failed: {self.ci.results.get('deep_scan_coverage')}")

    def test_gate4_joke_injection(self):
        passed = self.ci.gate_joke_injection()
        self.assertTrue(passed, f"Gate 4 failed: {self.ci.results.get('joke_injection')}")

    def test_gate5_dialogue_invariants(self):
        passed = self.ci.gate_dialogue_invariants()
        self.assertTrue(passed, f"Gate 5 failed: {self.ci.results.get('dialogue_invariants')}")

    def test_gate6_anti_ai_linter(self):
        passed = self.ci.gate_anti_ai_linter()
        self.assertTrue(passed, f"Gate 6 failed: {self.ci.results.get('anti_ai_linter')}")

    def test_run_all_gates(self):
        all_passed = self.ci.run_all_gates()
        self.assertTrue(all_passed)

    def test_cli_ci_hybrid(self):
        """Verifies python tools/ci_hybrid.py CLI runs with exit code 0."""
        cmd = [sys.executable, "tools/ci_hybrid.py"]
        res = subprocess.run(
            cmd,
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, f"CLI stderr: {res.stderr}")
        self.assertIn("HYBRID CI VERDICT: ALL GATES PASS (SUCCESS)", res.stdout)


if __name__ == "__main__":
    unittest.main()
