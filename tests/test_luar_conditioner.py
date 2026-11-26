import json
import os
import socket
import subprocess
import sys
import time
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import numpy as np

from prose_engine.conditioner import plan_conditioning
from prose_engine.influence import Influence
from prose_engine.reference_policy import PolicyEditor, ReferencePolicy, restricted_drive
from prose_engine.reference_service import prepare_retrieval
from prose_engine.style_engine import STANDARD_DRAMATIC
from prose_engine.voice.luar import LuarDrive, LuarIndex
from tests.test_engine import BAD, AppendingProvider


class Encoder:
    def encode(self, texts):
        return np.array([[1., 0.] if "noticed" in t else [0., 1.] for t in texts], dtype="float32")


class Provider(AppendingProvider):
    name = "mock"
    def __init__(self):
        self.prompts = []

    def generate_rewrite(self, request, prompt):
        self.prompts.append(prompt)
        return super().generate_rewrite(request, prompt)


class LuarConditionerTests(unittest.TestCase):
    def drive(self, encoder=None):
        index = LuarIndex(np.eye(2, dtype="float32"), ["eligible reference", "off reference"],
                          [{"book": "yes"}, {"book": "off"}])
        policy = ReferencePolicy({
            "yes": {"enabled": True, "permissions": ["rank_local", "prompt", "remote_transfer"]},
            "off": {"enabled": True, "permissions": ["rank_local", "prompt", "remote_transfer"]},
        })
        return restricted_drive(LuarDrive(index, encoder or Encoder()), policy,
                                ("rank_local", "prompt", "remote_transfer"), Influence({"off": 0}))

    def test_actual_conditioner_scores_with_allowed_index_and_no_luar_threshold(self):
        provider = Provider()
        drive = self.drive()
        with tempfile.TemporaryDirectory() as books:
            proposals = plan_conditioning(BAD, provider, STANDARD_DRAMATIC, drive=drive, books_dir=books)
        self.assertEqual(len(provider.prompts), 1)
        self.assertIn("eligible reference", provider.prompts[0])
        self.assertNotIn("off reference", provider.prompts[0])
        self.assertEqual(proposals[0].references, [])  # Prompt permission does not imply export permission.
        self.assertEqual(proposals[0].original_similarity, 1.0)
        self.assertEqual(proposals[0].rewrite_similarity, 0.0)
        self.assertNotIn("off-voice (corpus similarity", proposals[0].reason)

    def test_empty_and_zero_vectors_have_no_hits(self):
        drive = self.drive()
        drive.encoder = type("Zero", (), {"encode": lambda self, xs: np.zeros((len(xs), 2))})()
        self.assertEqual(drive.score_text("")["count"], 0)
        self.assertEqual(drive.score_text("nonempty")["count"], 0)
        self.assertEqual(drive.retrieve_passages("test", "text"), [])

    def test_preflight_failure_prevents_provider_dispatch(self):
        class Broken:
            def encode(self, xs):
                raise ValueError("synthetic model failure")
        provider = Provider()
        with tempfile.TemporaryDirectory() as books:
            result = plan_conditioning(BAD, provider, STANDARD_DRAMATIC, drive=self.drive(Broken()), books_dir=books)
        self.assertEqual(provider.prompts, [])
        self.assertFalse(result[0].accepted)
        self.assertIn("retrieval unavailable before generation", result[0].reason)

    def test_unconfigured_drive_cannot_bypass_eligibility(self):
        raw = LuarDrive(LuarIndex(np.eye(2), ["a", "b"], [{"book":"a"}, {"book":"b"}]), Encoder())
        provider = Provider()
        with tempfile.TemporaryDirectory() as books, self.assertRaisesRegex(ValueError, "no source policy"):
            plan_conditioning(BAD, provider, STANDARD_DRAMATIC, drive=raw, books_dir=books)
        self.assertEqual(provider.prompts, [])

    def test_nonfinite_preflight_score_prevents_dispatch(self):
        drive=self.drive()
        drive.score_text=lambda _: {"mean_top":float("nan")}
        provider=Provider()
        with tempfile.TemporaryDirectory() as books:
            result=plan_conditioning(BAD,provider,STANDARD_DRAMATIC,drive=drive,books_dir=books)
        self.assertFalse(result[0].accepted)
        self.assertIn("non-finite",result[0].reason)
        self.assertEqual(provider.prompts,[])

    def test_rank_only_or_local_prompt_drive_cannot_bypass_transfer_policy(self):
        index=LuarIndex(np.eye(2),["a","b"],[{"book":"yes"},{"book":"off"}])
        policy=ReferencePolicy({"yes":{"enabled":True,"permissions":["rank_local","prompt"]}})
        local=restricted_drive(LuarDrive(index,Encoder()),policy,("rank_local","prompt"))
        provider=Provider()
        provider.name="codex-session"
        with tempfile.TemporaryDirectory() as books, self.assertRaisesRegex(ValueError,"not authorized"):
            plan_conditioning(BAD,provider,STANDARD_DRAMATIC,drive=local,books_dir=books)
        self.assertEqual(provider.prompts,[])

    def test_score_failure_after_response_keeps_candidate_and_rejects_it(self):
        class LateFailure:
            calls = 0
            def encode(self, xs):
                self.calls += 1
                if self.calls == 3:
                    raise ValueError("synthetic score failure")
                return np.array([[1., 0.]])
        provider = Provider()
        with tempfile.TemporaryDirectory() as books:
            result = plan_conditioning(BAD, provider, STANDARD_DRAMATIC, drive=self.drive(LateFailure()), books_dir=books)
        self.assertEqual(len(provider.prompts), 1)
        self.assertFalse(result[0].accepted)
        self.assertTrue(result[0].proposed)
        self.assertIn("retrieval score unavailable", result[0].reason)

    def test_unconfigured_missing_corrupt_and_ready_status(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            self.assertEqual(prepare_retrieval(root, "luar", "mock").state, "unconfigured")
            (root / "reference_policy.json").write_text(json.dumps({"schema_version": 1, "sources": {
                "yes": {"enabled": True, "permissions": ["rank_local", "prompt"]}}}), encoding="utf-8")
            self.assertEqual(prepare_retrieval(root, "luar", "mock").state, "unavailable")
            path = root / "luar_index.joblib"
            path.write_bytes(b"corrupt")
            self.assertEqual(prepare_retrieval(root, "luar", "mock").state, "unavailable")
            LuarIndex(np.eye(2), ["yes", "no"], [{"book":"yes"}, {"book":"no"}]).save(path)
            with patch("prose_engine.voice.luar.LuarEncoder", return_value=Encoder()):
                setup = prepare_retrieval(root, "luar", "mock")
            self.assertEqual(setup.state, "ready")
            self.assertEqual(setup.drive.index.texts, ["yes"])

    def test_policy_editor_keeps_other_settings_and_rejects_stale_or_unknown_sources(self):
        with tempfile.TemporaryDirectory() as root:
            editor = PolicyEditor(root)
            metadata = [{"book": "yes"}, {"book": "off"}]
            initial = editor.snapshot(metadata, Influence({"off": 0}))
            self.assertEqual(initial["revision"], "missing")
            self.assertFalse(initial["sources"][0]["enabled"])
            editor.update("yes", True, ["rank_local", "prompt"], initial["revision"], {"yes", "off"})
            first = editor.snapshot(metadata, Influence({"off": 0}))
            with self.assertRaisesRegex(ValueError, "changed"):
                editor.update("off", True, ["rank_local"], initial["revision"], {"yes", "off"})
            with self.assertRaisesRegex(ValueError, "Invalid"):
                editor.update("unknown", True, ["rank_local"], first["revision"], {"yes", "off"})
            editor.update("off", True, ["rank_local"], first["revision"], {"yes", "off"})
            last = editor.snapshot(metadata, Influence({"off": 0}))
            yes = next(s for s in last["sources"] if s["id"] == "yes")
            off = next(s for s in last["sources"] if s["id"] == "off")
            self.assertEqual(yes["permissions"], ["rank_local", "prompt"])
            self.assertTrue(off["influence_off"])

    def test_workbench_and_conditioner_share_policy_before_provider(self):
        from tools.workbench import Workbench
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            books = root / "books"
            books.mkdir()
            LuarIndex(np.eye(2), ["eligible reference", "off reference"],
                      [{"book":"yes"}, {"book":"off"}]).save(books/"luar_index.joblib")
            (books/"reference_policy.json").write_text(json.dumps({"schema_version":1,"sources":{
                "yes":{"enabled":True,"permissions":["rank_local","prompt","remote_transfer"]},
                "off":{"enabled":True,"permissions":["rank_local","prompt","remote_transfer"]}}}), encoding="utf-8")
            (books/"influence.json").write_text(json.dumps({"books":{"off":0}}), encoding="utf-8")
            scene=root/"scene.txt"
            scene.write_text(BAD,encoding="utf-8")
            provider=Provider()
            provider.name = "codex-session"
            old = Path.cwd()
            try:
                os.chdir(root)
                with patch("prose_engine.voice.luar.LuarEncoder", return_value=Encoder()):
                    bench=Workbench(scene,root/"out",provider,telemetry_dir=root/"telemetry")
                    self.assertEqual(bench.retrieval_state,"ready")
                    bench.rewrite(0,0.5)
                self.assertTrue(provider.prompts)
                self.assertIn("eligible reference",provider.prompts[-1])
                self.assertNotIn("off reference",provider.prompts[-1])
            finally:
                os.chdir(old)

    def test_workbench_policy_http_requires_origin_and_preserves_stale_edits(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            books = root / "books"
            books.mkdir()
            LuarIndex(np.eye(2), ["a", "b"], [{"book":"yes"}, {"book":"off"}]).save(books/"luar_index.joblib")
            scene = root / "scene.txt"
            scene.write_text(BAD, encoding="utf-8")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            proc = subprocess.Popen([sys.executable, "-B", str(repo/"tools/workbench.py"),
                "--file", str(scene), "--out", str(root/"out"), "--provider", "mock", "--port", str(port)],
                cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            def get(path):
                with urllib.request.urlopen(base+path, timeout=2) as response:
                    return json.load(response)
            def post(data, origin):
                req=urllib.request.Request(base+"/api/reference-policy",data=json.dumps(data).encode(),
                    headers={"Content-Type":"application/json","Origin":origin})
                with urllib.request.urlopen(req,timeout=5) as response:
                    return json.load(response)
            try:
                for _ in range(100):
                    try:
                        initial=get("/api/reference-policy")
                        break
                    except (OSError, urllib.error.URLError):
                        if proc.poll() is not None:
                            self.fail("Workbench exited before starting")
                        time.sleep(.1)
                else:
                    self.fail("Workbench did not start")
                self.assertEqual(initial["revision"], "missing")
                edit={"source":"yes","enabled":False,"permissions":["rank_local"],"revision":"missing"}
                with self.assertRaises(urllib.error.HTTPError) as forbidden:
                    post(edit,"http://example.invalid")
                self.assertEqual(forbidden.exception.code,403)
                self.assertFalse((books/"reference_policy.json").exists())
                self.assertEqual(post(edit,base)["retrieval_state"],"no_eligible")
                with self.assertRaises(urllib.error.HTTPError) as stale:
                    post(edit,base)
                self.assertEqual(stale.exception.code,400)
                saved=json.loads((books/"reference_policy.json").read_text(encoding="utf-8"))
                self.assertFalse(saved["sources"]["yes"]["enabled"])
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)

    def test_condition_cli_uses_policy_and_does_not_export_prompt_only_reference(self):
        from prose_engine.cli import build_parser, cmd_condition
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            books=root/"books"
            books.mkdir()
            LuarIndex(np.eye(2), ["eligible reference","off reference"],
                      [{"book":"yes"},{"book":"off"}]).save(books/"luar_index.joblib")
            (books/"reference_policy.json").write_text(json.dumps({"schema_version":1,"sources":{
                "yes":{"enabled":True,"permissions":["rank_local","prompt"]},
                "off":{"enabled":True,"permissions":["rank_local","prompt"]}}}),encoding="utf-8")
            (books/"influence.json").write_text(json.dumps({"books":{"off":0}}),encoding="utf-8")
            scene=root/"scene.txt"
            scene.write_text(BAD,encoding="utf-8")
            provider=Provider()
            args=build_parser().parse_args(["condition","--file",str(scene),"--out",str(root/"out"),
                "--books",str(books),"--provider","mock","--style","standard_dramatic","--retrieval","luar",
                "--allow-book-references","--world-file",str(root/"missing.json"),"--house",str(root/"missing")])
            with patch("prose_engine.voice.luar.LuarEncoder",return_value=Encoder()), \
                 patch("prose_engine.cli.create_prose_provider",return_value=provider), \
                 patch("prose_engine.conditioner.persist_proposals"):
                self.assertEqual(cmd_condition(args),0)
            self.assertIn("eligible reference",provider.prompts[0])
            self.assertNotIn("off reference",provider.prompts[0])
            saved=(root/"out"/"proposals.json").read_text(encoding="utf-8")
            self.assertNotIn("eligible reference",saved)


if __name__ == "__main__":
    unittest.main()
