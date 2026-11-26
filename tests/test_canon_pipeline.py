"""End-to-end tests for Pass 0-3 canon ingestion compiler, Cook receipt audit, and Studio APIs."""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from prose_engine.canon_classifier import classify_blocks
from prose_engine.cook import run_cook_pipeline
from prose_engine.fact_extractor import run_canon_passes
from story_graph.canon_models import StoryCoord
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore
from story_graph.seeds.afm_seed import DEFAULT_AFM_UNIVERSE, seed_afm_universe
from tools.studio_ui import StudioRequestHandler, form_targets


class CanonPipelineTests(unittest.TestCase):
    def test_classifier_and_extractor_handle_speech_acts_and_new_delta_proposals(self):
        blocks = [
            {"id": "b1", "kind": "narrator", "text": "Rainee joked softly."},
            {"id": "b2", "kind": "character", "speaker": "rainee", "text": "Just kidding—look at your husband Jeff."},
            {"id": "b3", "kind": "narrator", "text": "Francine never married Stan Smith and kept the Ling name."},
            {"id": "b4", "kind": "narrator", "text": "Jeff used the device to become Jess during intimacy with Haley."},
            {"id": "b5", "kind": "narrator", "text": "Francine Smith waited by the stove."},
        ]
        spans = classify_blocks(blocks)
        by_block = {s.block_id: s.assertion_class for s in spans}
        self.assertEqual(by_block["b2"], "dialogue_teasing")
        self.assertEqual(by_block["b3"], "negated_divergence")
        self.assertEqual(by_block["b4"], "narration_fact")
        self.assertEqual(by_block["b5"], "narration_fact")

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            seed_afm_universe(conn, universe_id=DEFAULT_AFM_UNIVERSE)
            coord = StoryCoord(DEFAULT_AFM_UNIVERSE, "main", "spring-break", 10.0, 0)
            report = run_canon_passes(blocks, coord, conn, queue_proposals=True)
            # b2 teasing exempt, b3 negated_divergence exempt, b4 missing Jess device at spring-break, b5 Smith bleed
            codes = {f["code"] for f in report["conflicts"]}
            self.assertIn("SHOW_IMPORT_BLEED", codes)
            self.assertIn("DEVICE_ANACHRONISM", codes)
            self.assertTrue(any(f["code"] == "TEASING_DIALOGUE_EXEMPT" for f in report["advisories"]))
            self.assertEqual(len(report["queued_proposals"]), 1)
        finally:
            conn.close()

    def test_cook_pipeline_emits_canon_audit_and_studio_endpoints_manage_proposals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "timeline.sqlite"
            forms_path = root / "character-forms.sqlite"
            timeline = TimelineStore(db_path)
            forms = FormGraphStore(forms_path, form_targets())
            timeline.add_starter_cards()
            script = (
                "INT. GYM - DAY\n\n"
                "Haley thought about her husband Jeff while cheating with Holly Graham.\n"
            )
            timeline.save("hot-scoomp", 0, script=script, source_name="draft")
            cook_result = run_cook_pipeline(timeline, forms, "hot-scoomp")
            self.assertIn("canon_audit", cook_result["receipt"])
            self.assertEqual(cook_result["receipt"]["canon_audit"]["conflicts"], 0)

            server = ThreadingHTTPServer(("127.0.0.1", 0), StudioRequestHandler)
            server.timeline_path = db_path
            server.timeline_only = True
            server.form_graph = forms
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"

            def post(path: str, body: dict) -> dict:
                req = urllib.request.Request(
                    base + path,
                    data=json.dumps(body).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Origin": base},
                )
                with urllib.request.urlopen(req) as resp:
                    return json.load(resp)

            try:
                diff = post("/api/canon-diff", {
                    "episode": "hot-scoomp",
                    "episode_position": 20.0,
                    "beat": 2,
                    "text": "Jeff used the device to transform into Jess for Haley.",
                    "queue_proposals": True,
                })
                self.assertEqual(len(diff["queued_proposals"]), 1)
                pid = diff["queued_proposals"][0]

                opened_before = post("/api/canon-proposals", {"action": "open", "episode": "hot-scoomp", "beat": 2})
                self.assertEqual(len(opened_before["proposals"]), 1)
                self.assertEqual(opened_before["proposals"][0]["proposal_id"], pid)

                resolved = post("/api/canon-proposals", {
                    "action": "resolve",
                    "proposal_id": pid,
                    "decision": "accepted",
                    "reviewer": "Author",
                })
                self.assertEqual(resolved["status"], "accepted")
                delta_id = resolved["applied_id"]

                after_accept = post("/api/canon-diff", {
                    "episode": "hot-scoomp",
                    "episode_position": 20.0,
                    "beat": 2,
                    "text": "Jeff used the device to transform into Jess for Haley.",
                })
                self.assertEqual(after_accept["conflicts"], [])
                self.assertEqual(after_accept["supported"][0]["code"], "DEVICE_SALVAGE_SUPPORTED")

                # Undo / retire the delta cleanly
                undone = post("/api/canon-proposals", {"action": "retire_delta", "delta_id": delta_id, "retired": True})
                self.assertTrue(undone["retired"])
                after_undo = post("/api/canon-diff", {
                    "episode": "hot-scoomp",
                    "episode_position": 20.0,
                    "beat": 2,
                    "text": "Jeff used the device to transform into Jess for Haley.",
                })
                self.assertTrue(any(f["code"] == "DEVICE_ANACHRONISM" for f in after_undo["conflicts"]))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
