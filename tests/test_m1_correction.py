"""M1 contracts: cut-first, frozen dialogue, entity gate, present tense, persistence."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prose_engine.conditioner import (
    Proposal,
    apply_proposals,
    is_dialogue,
    persist_proposals,
    plan_conditioning,
)
from prose_engine.diagnostics import ProseDiagnosticsAnalyzer
from prose_engine.guards import introduced_entities
from prose_engine.style_engine import STANDARD_DRAMATIC
from telemetry.engine_run_logger import EngineRunLogger


class RewriteProvider:
    model_name = "rewrite"

    def __init__(self, text):
        self.text = text
        self.calls = 0

    def generate_rewrite(self, request, prompt):  # noqa: ARG002
        self.calls += 1
        return self.text


class NoCallProvider:
    model_name = "no-call"

    def generate_rewrite(self, request, prompt):  # noqa: ARG002
        raise AssertionError("deletion must not call the provider")


DIALOGUE = "- She felt the room was cold, and she noticed the door was open, and she saw the table."


class CutFirstTests(unittest.TestCase):
    def test_dialogue_frozen_by_default(self):
        provider = RewriteProvider("- The room was cold. The door stood open. The table waited.")
        proposals = plan_conditioning(DIALOGUE, provider, STANDARD_DRAMATIC)
        self.assertEqual(proposals, [])
        self.assertEqual(provider.calls, 0)

    def test_dialogue_can_be_allowed(self):
        provider = RewriteProvider("- The room was cold. The door stood open. The table waited.")
        proposals = plan_conditioning(DIALOGUE, provider, STANDARD_DRAMATIC, allow_dialogue=True)
        self.assertGreaterEqual(len(proposals), 1)

    def test_kept_dialogue_from_brief_is_frozen(self):
        provider = RewriteProvider("- The room was cold. The door stood open. The table waited.")
        proposals = plan_conditioning(DIALOGUE, provider, STANDARD_DRAMATIC, frozen=[DIALOGUE])
        self.assertEqual(proposals, [])

    def test_deletion_proposal_applies(self):
        text = (
            "Mara pushed the heavy door open with one hand and stepped inside. "
            "She noticed the room was empty."
        )
        proposals = plan_conditioning(text, NoCallProvider(), STANDARD_DRAMATIC)
        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.op, "delete")
        self.assertTrue(proposal.accepted, proposal.reason)
        self.assertIn("noticed", proposal.removed_text)
        updated, applied = apply_proposals(text, proposals)
        self.assertEqual(applied, 1)
        self.assertNotIn("noticed", updated)

    def test_invented_entity_rejected(self):
        text = ("Mara noticed the door was open. She felt the chill of the empty room "
                "and listened to the hall.")
        provider = RewriteProvider("Mara stood in the doorway. Detective Marsh crossed the room.")
        proposals = plan_conditioning(text, provider, STANDARD_DRAMATIC)
        self.assertGreaterEqual(len(proposals), 1)
        self.assertFalse(proposals[-1].accepted)
        self.assertIn("new entities", proposals[-1].reason)

    def test_present_tense_is_flagged(self):
        report = ProseDiagnosticsAnalyzer.analyze("Mara notices the door. She feels a chill.")
        self.assertGreater(report.filter_word_count, 0)

    def test_introduced_entities_helper(self):
        found = introduced_entities("Mara waited.", "Mara waited. Detective Marsh arrived.")
        self.assertIn("Detective", found)
        self.assertIn("Marsh", found)

    def test_persist_keeps_accepts_and_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposals.jsonl"
            rows = [
                Proposal(0, 0, 10, "a", "b", [], True, "ok", op="delete", removed_text="x"),
                Proposal(1, 11, 20, "c", "d", [], False, "drops facts"),
            ]
            runs = Path(tmp) / "engine_runs"
            with patch.object(EngineRunLogger, "RUNS_DIR", runs):
                persist_proposals(rows, path, "scene.md")
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0]["op"], "delete")
            self.assertFalse(lines[1]["accepted"])
            self.assertTrue((runs / "LATEST_RUN_LOG.md").is_file())

    def test_dialogue_detection(self):
        self.assertTrue(is_dialogue("- Absolutely not."))
        self.assertTrue(is_dialogue("Stan: Hey."))
        self.assertFalse(is_dialogue("Rainee sets the lipstick down."))


if __name__ == "__main__":
    unittest.main()
