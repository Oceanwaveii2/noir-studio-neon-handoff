"""Tests for tools.workbench: span flagging, Blind A/B, and telemetry logging."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from tools.workbench import Workbench, PAGE
from prose_engine.editorial_revisions import RevisionError, RevisionStore


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.scene_file = self.temp_path / "scene.md"
        self.scene_file.write_text(
            "Rainee stood before the oval vanity mirror \u2014 waiting by the bedroom door \u2014 wondering if she felt the shift in the quiet morning air.\n\n"
            "**FRANCINE**\nEverything is going to be completely fine once we reach the summer house.\n\n"
            "Her heart pounded and her stomach dropped across the long wooden table as the door swung open slowly.",
            encoding="utf-8",
        )
        self.out_dir = self.temp_path / "out"

        self.mock_provider = MagicMock()
        self.mock_provider.generate_rewrite.return_value = "Rainee stood by the door, watching the hallway."

        self.bench = Workbench(self.scene_file, self.out_dir, self.mock_provider,
                               use_retrieval=False, telemetry_dir=self.temp_path / "telemetry")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_spans_exposed_in_workbench(self):
        self.assertEqual(len(self.bench.spans), len(self.bench.paragraphs))
        # Para 0 has double em-dash and filter verbs ('wondering', 'felt')
        rules_p0 = {s["rule"] for s in self.bench.spans[0]}
        self.assertIn("em_dash", rules_p0)
        self.assertIn("filter", rules_p0)

        # Para 1 is dialogue: spans should be empty
        self.assertEqual(self.bench.spans[1], [])

        # Para 2 has body_cliche
        rules_p2 = {s["rule"] for s in self.bench.spans[2]}
        self.assertIn("body_cliche", rules_p2)

    def test_js_syntax_error_not_in_page(self):
        # Line 117 bug check: ensure invalid '.passage[data-passage=""]' is gone
        self.assertNotIn('.passage[data-passage=""]', PAGE)
        self.assertIn("data-passage", PAGE)
        self.assertIn("blindAb", PAGE)

    def test_blind_ab_generates_token_and_shuffled_options(self):
        result = self.bench.blind_ab(0, strength=0.8)
        self.assertIn("token", result)
        self.assertEqual(result["index"], 0)
        self.assertIn("option1", result)
        self.assertIn("option2", result)
        self.assertTrue(result["option1"]["text"])
        self.assertTrue(result["option2"]["text"])

        # Check internal session
        token = result["token"]
        session = self.bench._blind_sessions[token]
        self.assertIn("provenance", session["option1"])
        self.assertIn("provenance", session["option2"])

    def test_choose_blind_ab_logs_to_telemetry(self):
        result = self.bench.blind_ab(0, strength=0.8)
        token = result["token"]

        choice_result = self.bench.choose_blind_ab(token, "1")
        self.assertIn("winner_provenance", choice_result)
        self.assertIn("loser_provenance", choice_result)
        self.assertIn("text", choice_result)

        log_path = self.temp_path / "telemetry" / "blind_ab.jsonl"
        self.assertTrue(log_path.is_file())
        lines = log_path.read_text(encoding="utf-8").splitlines()
        last_entry = json.loads(lines[-1])
        self.assertEqual(last_entry["token"], token)
        self.assertEqual(last_entry["choice"], "option1")
        self.assertIn("edit_distance", last_entry)
        self.assertIn("overlap_vs_original", last_entry)

    def test_reviewed_save_preserves_source_and_replays_after_undo(self):
        source = ("A copper bell rang twice in the courtyard while the attendant counted the chairs."
                  "\r\n\r\n- This line is protected and must remain exactly as it appears in this document.\r\n")
        self.scene_file.write_bytes(source.encode())
        start = source.index("- This")
        store = RevisionStore.create(self.temp_path / "review.sqlite", source, ((start, len(source) - 2),))
        bench = Workbench(self.scene_file, self.out_dir, self.mock_provider,
                          review_store=store, use_retrieval=False)
        with self.assertRaisesRegex(RevisionError, "revision store"):
            self.bench.save({"action": "preview"})
        locked = bench.save({"action": "preview", "base": 0, "edits": {"1": "Changed dialogue."}})
        self.assertEqual(locked["status"], "BLOCKED_FROZEN_SPAN")
        request = {"action": "preview", "base": 0, "edits": {"0": "A copper bell rang twice.\nThe attendant counted the chairs."}}
        result = bench.save(request)
        self.assertEqual(result["status"], "ELIGIBLE_FOR_REVIEW")
        apply = {**request, "action": "apply", "reviewer": "Fixture author", "operation_id": "wb-apply",
                 "candidate_hash": result["candidate_hash"], "world_hash": result["world_hash"]}
        self.assertEqual(bench.save(apply)["revision"], 1)
        self.assertEqual(store.current()[1], "A copper bell rang twice.\r\nThe attendant counted the chairs." + source[source.index("\r\n"):])
        self.assertEqual(bench.save({"action":"undo","base":1,"reviewer":"Fixture author","operation_id":"wb-undo"})["revision"], 2)
        self.assertEqual(bench.save(apply)["revision"], 1)
        self.assertEqual(store.current()[0], 2)
        self.assertEqual(self.scene_file.read_bytes(), source.encode())
        self.assertFalse(self.out_dir.exists())


if __name__ == "__main__":
    unittest.main()
