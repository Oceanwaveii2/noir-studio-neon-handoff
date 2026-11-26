"""Exercise the editor boundary used by every local inference arm."""

from dataclasses import replace
from hashlib import sha256
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from prose_engine.editorial_service import Edit, preview
from prose_engine.local_trial import assess, deterministic, parse_proposal, synthetic_case
from prose_engine.voice.spatial import House
from prose_engine.voice.world_state import WorldState
from tools.run_local_u7 import load_cases, trial

ROOT = Path(__file__).resolve().parents[1]


def proposal(text):
    return json.dumps({"operation": "replace", "replacement": text})


class U7LocalTrialTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = json.loads((ROOT / "eval/u7_local_protocol.json").read_bytes())
        cls.cases = {row["id"]: synthetic_case(row) for row in cls.protocol["smoke"]}
        cls.world = WorldState(banned=[{"pattern": r"\bhusband\b", "why": "Jeff is a boyfriend."}])
        cls.house = House.load(ROOT / "books/ling_house")

    def check(self, name, output):
        return assess(self.cases[f"smoke-{name}"], output, self.world, self.house)["status"]

    def test_protocol_refuses_source_drift_before_loading_other_inputs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "draft.md").write_bytes(b"Revised text.")
            protocol = {**self.protocol, "source": "draft.md", "source_sha256": sha256(b"Original text.").hexdigest()}
            with patch("tools.run_local_u7.ROOT", root):
                with self.assertRaisesRegex(ValueError, "Frozen input changed: source"):
                    load_cases(protocol)

    def test_failed_smoke_arm_stops_while_other_arm_continues(self):
        clean = self.cases["smoke-clean-cut"]
        held_out = replace(clean, id="held-out-fixture", split="held_out")
        methods = {
            "broken": lambda _: {"raw": "invalid"},
            "clean": lambda _: {"raw": '{"operation":"keep","replacement":""}'},
        }
        receipts = []
        with redirect_stdout(StringIO()):
            result = trial([*self.cases.values(), held_out], methods, self.world, self.house, receipts.append)
        self.assertEqual(5, result["broken"]["smoke"]["outcomes"]["SCHEMA_FAILURE"])
        self.assertNotIn("held_out", result["broken"])
        self.assertEqual(1, result["clean"]["held_out"]["outcomes"]["KEEP"])
        self.assertEqual(["clean"], [row["method"] for row in receipts if row["split"] == "held_out"])

    def test_strict_contract_rejects_invalid_or_ambiguous_output(self):
        bad = (
            'not JSON',
            '{"operation":"keep","operation":"replace","replacement":"Changed."}',
            '{"operation":"keep","replacement":"This would hide an edit."}',
            '{"operation":"replace","replacement":"Two\\nlines."}',
            '{"operation":"replace","replacement":""}',
            '{"operation":"replace","replacement":"Changed.","start":0}',
        )
        for raw in bad:
            with self.subTest(raw=raw):
                self.assertEqual("SCHEMA_FAILURE", self.check("clean-cut", raw))
        self.assertEqual(("keep", ""), parse_proposal('{"operation":"keep","replacement":""}'))

    def test_valid_json_cannot_override_frozen_conflict(self):
        self.assertEqual("BLOCKED_FROZEN_SPAN",
                         self.check("frozen-dialogue", proposal("- My boyfriend Jeff is waiting.")))
        self.assertEqual("KEEP", self.check("frozen-dialogue", deterministic(self.cases["smoke-frozen-dialogue"])))

    def test_valid_json_cannot_introduce_canon_or_reveal_visitor(self):
        self.assertEqual("BLOCKED_NEW_CANON_ISSUE",
                         self.check("future-form", proposal("held a coffee cup beside her husband in the living room")))
        self.assertTrue(self.check("future-form", proposal("held a coffee cup in the living room, tail twitching"))
                        .startswith("BLOCKED_"))
        self.assertTrue(self.check("unknown-visitor", proposal("She waited for Roger to answer."))
                        .startswith("BLOCKED_"))

    def test_valid_json_cannot_duplicate_span_boundary(self):
        self.assertEqual("BLOCKED_SPAN_BOUNDARY",
                         self.check("future-form", proposal("gripped a coffee cup in the living room.")))

    def test_only_target_bytes_change_in_unicode_preview(self):
        case = self.cases["smoke-unicode-frozen"]
        result = assess(case, deterministic(case), self.world, self.house)
        self.assertEqual("ELIGIBLE", result["status"])
        candidate = preview(case.source, case.revision,
                            (Edit(case.id, case.start, case.end, case.target, result["replacement"]),),
                            case.frozen, self.world).candidate.encode("utf-8")
        self.assertEqual('“Hold there.”\r\n\r\nStella set the Étoile box by the door. The handle was cold.\r\n'
                         .encode("utf-8"), candidate)

    def test_stale_anchor_cannot_propose_a_replacement(self):
        case = replace(self.cases["smoke-clean-cut"], revision="stale")
        self.assertEqual("STALE_REVISION", assess(case, deterministic(case), self.world, self.house)["status"])
