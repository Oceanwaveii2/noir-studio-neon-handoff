"""Release boundary and telemetry behavior fixtures."""
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from prose_engine.conditioner import Proposal, persist_proposals
from prose_engine.editorial_revisions import RevisionStore, world_revision
from prose_engine.editorial_service import Edit, preview, revision
from prose_engine.voice.world_state import WorldState
from telemetry.engine_run_logger import EngineRunLogger
from tools.u8_recovery import recover
from tools import ci
from tools.release_tests import is_model_case


class TelemetryBoundaryTests(unittest.TestCase):
    def test_editorial_cliche_findings_reach_the_saved_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposals = [
                Proposal(0, 0, 10, "original", "A baritone trombone sounded.", [], False, "blacklisted cliché"),
                Proposal(1, 11, 20, "other", "A clean line.", [], True, "ok"),
            ]
            with patch.object(EngineRunLogger, "RUNS_DIR", root / "runs"):
                persist_proposals(proposals, root / "proposals.jsonl", "fixture")
            reports = list((root / "runs").glob("run_*.json"))
            self.assertEqual(len(reports), 1)
            report = json.loads(reports[0].read_bytes())
            self.assertIn("baritone trombone", report["entries"][0]["blacklisted_cliches_caught"])
            self.assertEqual(report["entries"][1]["blacklisted_cliches_caught"], [])
            self.assertGreater(report["metrics"]["ai_cliches_blocked"], 0)
            self.assertEqual(report["metrics"]["proposals_accepted"], 1)
            self.assertEqual(report["metrics"]["proposals_rejected"], 1)

    def test_mismatched_findings_do_not_write_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs"
            with patch.object(EngineRunLogger, "RUNS_DIR", path):
                with self.assertRaisesRegex(ValueError, "each proposal"):
                    EngineRunLogger.log_run("fixture", [object()], "", "", cliche_findings=[])
            self.assertFalse(path.exists())


class RecoveryTests(unittest.TestCase):
    def test_backup_restores_approved_revision_and_history_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = RevisionStore.create(root / "source.sqlite", "A clear door.", ())
            world = WorldState()
            edit = Edit("word", 2, 7, "clear", "closed")
            result = preview("A clear door.", revision("A clear door."), (edit,), (), world)
            store.apply("approved-1", 0, (edit,), "fixture reviewer",
                        revision(result.candidate), world_revision(world), world)
            receipt = recover(store.path, root / "backup")
            self.assertEqual(receipt["revision_history"]["head"], 1)
            self.assertEqual(receipt["revision_history"]["revision_count"], 2)
            self.assertEqual(RevisionStore(root / "backup/restored.sqlite").current()[1], "A closed door.")
            with self.assertRaises(FileExistsError):
                recover(store.path, root / "backup")


class ReleaseControlTests(unittest.TestCase):
    def test_code_manifest_excludes_data_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "manifest.sha256"
            command = [sys.executable, "-B", "tools/manifest.py", "--out", str(target)]
            first = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(first.returncode, 0, first.stderr)
            original = target.read_bytes()
            names = [line.split("  ", 1)[1] for line in original.decode("utf-8").splitlines()]
            self.assertIn("pyproject.toml", names)
            self.assertIn("tools/v2_page.html", names)
            self.assertIn("tools/workbench_remote.py", names)
            self.assertIn("prose_engine/service_daemon.py", names)
            self.assertTrue(all(name == "pyproject.toml" or name.startswith(
                ("prose_engine/", "story_graph/", "telemetry/", "tools/")) for name in names))
            self.assertFalse(any(name.endswith(('.sqlite','.joblib','.md','.jsonl')) or 'recover.py' in name for name in names))
            second = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(target.read_bytes(), original)

    def test_model_dependent_cases_are_separate_from_ordinary_checks(self):
        self.assertTrue(is_model_case("tests.test_voice_steer.SteeringTests.test_example"))
        self.assertTrue(is_model_case("unittest.loader._FailedTest.tests.test_coprocessor_reranker"))
        self.assertTrue(is_model_case("tests.test_coprocessor_harness.TestDualEngineHarness.test_hybrid_mode_cuda_coprocessor_activation"))
        self.assertFalse(is_model_case("tests.test_coprocessor_harness.TestDualEngineHarness.test_rule_based_mode"))

    def test_timeout_is_reported_and_manifest_is_not_published(self):
        calls = []
        def run(command, **kwargs):
            calls.append((command, kwargs))
            if "tools/verify.py" in command:
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch("sys.argv", ["ci.py"]), patch.object(ci.subprocess, "run", side_effect=run), redirect_stdout(StringIO()) as output:
            self.assertEqual(ci.main(), 1)
        self.assertIn("[BLOCKED] verify: exceeded 300 s", output.getvalue())
        self.assertIn("[NOT RUN] manifest", output.getvalue())
        self.assertTrue(all(kwargs["env"]["HF_HUB_OFFLINE"] == "1" for _, kwargs in calls))
        self.assertFalse(any("tools/manifest.py" in command for command, _ in calls))
