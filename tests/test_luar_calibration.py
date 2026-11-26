import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from prose_engine.voice.luar_calibration import evaluate
from tools.score_luar_calibration import score_pairs, main as score_main


def fixture(kind="synthetic"):
    data = {"schema_version": 1, "evidence_kind": kind, "pipeline": {
        "backend": "luar", "model": "synthetic", "model_revision": "fixture-v1",
        "preprocessing": "fixture-v1", "index_sha256": "a"*64, "policy_sha256": "b"*64,
        "influence_sha256": "c"*64},
        "examples": []}
    for split in ("development", "held_out"):
        for label in ("acceptable", "off_voice"):
            for i in range(10):
                after = .78 if label == "acceptable" else .45
                data["examples"].append({"id":f"{split}-{label}-{i}",
                    "document_id":f"{split}-{label}-{i}", "split":split, "decision":label,
                    "before":.8, "after":after, "reviewer":"synthetic-reviewer",
                    "evidence":"synthetic-case"})
    return data


class LuarCalibrationTests(unittest.TestCase):
    def test_selects_on_development_and_reports_held_out_without_enabling_gate(self):
        result=evaluate(fixture())
        self.assertEqual(result["status"],"synthetic_only")
        self.assertTrue(result["criteria_met"])
        self.assertEqual(result["held_out"]["false_rejections"],0)
        self.assertEqual(result["held_out"]["detections"],10)
        self.assertFalse(result["live_gate_changed"])

    def test_bad_held_out_does_not_retrain_or_claim_success(self):
        data=fixture("author_reviewed")
        for row in data["examples"]:
            if row["split"] == "held_out" and row["decision"] == "acceptable":
                row["after"]=.1
        result=evaluate(data)
        self.assertEqual(result["status"],"held_out_failed")
        self.assertEqual(result["held_out"]["false_rejections"],10)

    def test_small_or_missing_data_abstains(self):
        data=fixture()
        data["examples"]=data["examples"][:3]
        self.assertEqual(evaluate(data)["status"],"insufficient_evidence")

    def test_duplicate_id_and_cross_split_document_are_rejected(self):
        data=fixture()
        data["examples"][-1]["id"]=data["examples"][0]["id"]
        with self.assertRaisesRegex(ValueError,"Duplicate"): evaluate(data)
        data=fixture()
        data["examples"][-1]["document_id"]=data["examples"][0]["document_id"]
        with self.assertRaisesRegex(ValueError,"both splits"): evaluate(data)

    def test_labels_and_pipeline_must_be_explicit_and_no_passage_text(self):
        data=fixture("author_reviewed")
        del data["examples"][0]["reviewer"]
        with self.assertRaisesRegex(ValueError,"reviewer"): evaluate(data)
        data=fixture()
        data["examples"][0]["text"]="private passage"
        with self.assertRaisesRegex(ValueError,"not passage text"): evaluate(data)
        data=fixture()
        data["pipeline"]["index_sha256"]="missing"
        with self.assertRaisesRegex(ValueError,"SHA-256"): evaluate(data)
        data=fixture()
        data["examples"][0]["before"]=float("nan")
        with self.assertRaisesRegex(ValueError,"finite"): evaluate(data)

    def test_cli_writes_new_report_without_overwriting(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/"scores.json"
            target=Path(root)/"report.json"
            source.write_text(json.dumps(fixture()),encoding="utf-8")
            command=[sys.executable,"-B","tools/calibrate_luar.py","--file",str(source),"--out",str(target)]
            first=subprocess.run(command,capture_output=True,text=True,timeout=20)
            self.assertEqual(first.returncode,0,first.stderr)
            report=json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(report["status"],"synthetic_only")
            saved=target.read_bytes()
            second=subprocess.run(command,capture_output=True,text=True,timeout=20)
            self.assertEqual(second.returncode,2)
            self.assertEqual(target.read_bytes(),saved)

    def test_scoring_uses_adapter_and_does_not_write_passage_text(self):
        class Drive:
            def __init__(self): self.calls=[]
            def score_text(self, text):
                self.calls.append(text)
                return {"mean_top":.5,"count":1}
        example = {"id":"1","document_id":"scene1","split":"development","decision":"acceptable",
                   "original":"private original","candidate":"private candidate"}
        data = {"schema_version":1,"evidence_kind":"synthetic","examples":[example]}
        drive = Drive()
        result=score_pairs(data,drive,fixture()["pipeline"])
        self.assertEqual(drive.calls,["private original","private candidate"])
        self.assertNotIn("private",json.dumps(result))
        self.assertEqual(result["examples"][0]["before"],.5)
        data["examples"][0]["extra"]="not allowed"
        with self.assertRaisesRegex(ValueError,"Unknown"):
            score_pairs(data,drive,fixture()["pipeline"])

    def test_local_scoring_command_uses_ranking_only_and_never_overwrites(self):
        class Drive:
            encoder=SimpleNamespace(model_name="synthetic")
            def score_text(self, text): return {"mean_top":.5,"count":1}
        example={"id":"1","document_id":"scene","split":"development","decision":"acceptable",
                 "original":"private original","candidate":"private candidate"}
        data={"schema_version":1,"evidence_kind":"synthetic","examples":[example]}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"luar_index.joblib").write_bytes(b"index")
            (root/"reference_policy.json").write_text('{"schema_version":1,"sources":{}}',encoding="utf-8")
            source=root/"pairs.json"; source.write_text(json.dumps(data),encoding="utf-8")
            out=root/"scores.json"
            args=["--file",str(source),"--books",str(root),"--out",str(out)]
            with patch("tools.score_luar_calibration.prepare_retrieval",
                       return_value=SimpleNamespace(state="ready",drive=Drive())) as setup:
                self.assertEqual(score_main(args),0)
                self.assertEqual(setup.call_args.kwargs["purposes"],("rank_local",))
                saved=out.read_bytes()
                self.assertEqual(score_main(args),2)
                self.assertEqual(out.read_bytes(),saved)
            self.assertNotIn(b"private",saved)


if __name__ == "__main__":
    unittest.main()
