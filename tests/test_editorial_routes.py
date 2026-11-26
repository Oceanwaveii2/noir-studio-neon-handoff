import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from prose_engine.editorial_revisions import RevisionStore
from tools.studio_ui import StudioRequestHandler


class EditorialRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fixture = json.loads(Path("tests/fixtures/editorial_pilot.json").read_text(encoding="utf-8"))
        self.text = fixture["document"]
        self.dialogue, self.action, _ = fixture["beats"]
        start = self.text.index(self.dialogue["expected_text"])
        self.store = self.root / "store.sqlite"
        RevisionStore.create(self.store, self.text, ((start, start + len(self.dialogue["expected_text"])),))
        StudioRequestHandler.review_store_path = self.store
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), StudioRequestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        StudioRequestHandler.review_store_path = None

    def http(self, data, origin=True):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = self.url
        req = urllib.request.Request(self.url + "/api/editorial", data=json.dumps(data).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.load(response)

    def cli(self, data):
        path = self.root / "request.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        run = subprocess.run([sys.executable, "-B", "-m", "prose_engine", "editorial",
                              "--store", str(self.store), "--request", str(path)],
                             capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def test_same_preview_and_review_apply_undo(self):
        request = {"action": "preview", "base": 0, "expected": self.action["expected_text"],
                   "replacement": self.action["proposals"][0]["replacement"]}
        cli_result = self.cli(request)
        result = self.http(request)
        self.assertEqual(result, cli_result)
        self.assertEqual(result["status"], "ELIGIBLE_FOR_REVIEW")
        self.assertTrue(result["baseline_issues"])
        self.assertIn("--- current", result["diff"])
        apply = {**request, "action": "apply", "reviewer": "Test author", "operation_id": "test-apply",
                 "candidate_hash": result["candidate_hash"], "world_hash": result["world_hash"]}
        applied = self.http(apply)
        self.assertEqual(applied["revision"], 1)
        self.assertEqual(applied["author_decision"], "accepted")
        undo = {"action": "undo", "base": 1, "reviewer": "Test author", "operation_id": "test-undo"}
        self.assertEqual(self.http(undo)["revision"], 2)
        self.assertEqual(self.cli(apply), applied)
        self.assertEqual(self.cli(undo)["revision"], 2)
        with self.assertRaises(urllib.error.HTTPError):
            self.http({**apply, "replacement": "different"})
        with self.assertRaises(urllib.error.HTTPError):
            self.http({**undo, "operation_id": "new-undo"})
        self.assertEqual(self.cli({"action": "state"})["text"], self.text)

    def test_locked_stale_and_cross_origin(self):
        request = {"action": "preview", "base": 0, "expected": self.dialogue["expected_text"],
                   "replacement": self.dialogue["proposals"][0]["replacement"]}
        self.assertEqual(self.http(request)["status"], "BLOCKED_FROZEN_SPAN")
        with self.assertRaises(urllib.error.HTTPError):
            self.http({**request, "base": 99})
        with self.assertRaises(urllib.error.HTTPError):
            self.http(request, origin=False)

    def test_condition_apply_requires_review_and_matching_source(self):
        source = self.root / "source.md"
        source.write_bytes(self.text.encode())
        command = [sys.executable, "-B", "-m", "prose_engine", "condition", "--file", str(source), "--apply"]
        def run(args):
            return subprocess.run(command + args, capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(run([]).returncode, 2)
        request = {"action":"preview","base":0,"expected":self.action["expected_text"],
                   "replacement":self.action["proposals"][0]["replacement"]}
        reviewed = self.http(request)
        apply = {**request,"action":"apply","reviewer":"Fixture author","operation_id":"condition",
                 "world_hash":reviewed["world_hash"],"candidate_hash":reviewed["candidate_hash"]}
        payload = self.root / "apply.json"
        payload.write_text(json.dumps(apply), encoding="utf-8")
        args = ["--review-store",str(self.store),"--review-request",str(payload)]
        source.write_bytes(b"wrong source")
        self.assertIn("does not match", run(args).stderr)
        source.write_bytes(self.text.encode())
        result = run(args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["revision"], 1)
        self.assertEqual(source.read_bytes(), self.text.encode())

    def test_canon_and_analysis_counts(self):
        request = {"action": "preview", "base": 0, "expected": self.action["expected_text"],
                   "replacement": self.action["proposals"][1]["replacement"]}
        result = self.http(request)
        self.assertEqual(result["status"], "BLOCKED_NEW_CANON_ISSUE")
        self.assertTrue(result["new_issues"])
        req = urllib.request.Request(self.url + "/api/compute",
              data=json.dumps({"blocks": [{"text": self.text, "freeze": 100}]}).encode(),
              headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as response:
            computed = json.load(response)
        self.assertEqual((computed["accepted"], computed["rejected"]), (0, 0))
        self.assertEqual(computed["blocks"][0]["text"], self.text)
