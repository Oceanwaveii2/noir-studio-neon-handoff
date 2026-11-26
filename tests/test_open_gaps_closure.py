"""Regression tests closing engineering gaps NE-012, NE-013, NE-014, and NE-015."""
from __future__ import annotations

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prose_engine.editorial_adapter import dispatch as editorial_dispatch
from prose_engine.editorial_revisions import RevisionStore
from prose_engine.meaning_checks import assess_meaning, assess_semantic_review
from prose_engine.notebook import DraftStore, NotebookStore
from prose_engine.reference_service import RetrievalSetup
from prose_engine.scoped_pipeline import build_packet, validate_output
from prose_engine.scoped_service import (
    enforce_standalone_world_laws,
    execute_scoped,
    record_standalone_draft,
    resolve_default_timeline,
)
from prose_engine.voice.world_state import WorldState
from story_graph.character_forms import AFM_JUNCTIONS
from story_graph.character_profiles import CharacterProfileStore
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore
from tools import test_retrieval, workbench
from tools.studio_canon_routes import run_craft_brief


class _StaticProvider:
    name = "static-test"

    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def generate_rewrite(self, request, prompt):
        self.calls += 1
        return self.text


class OpenGapsClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "timeline.sqlite"
        self.store = TimelineStore(self.db_path, project_id="project", universe_id="universe")
        self.store.add_starter_cards()
        self.store.save("spring-break", 0, script="A quiet room in the Ling house.", source_name="fixture")
        self.store.add_event(
            "future-secret",
            "tapped-out",
            1,
            "Confidential sapphire blueprint lies in the vault.",
            status="approved",
            permitted=True,
            source_id="future-fixture",
            reviewer="author",
        )
        self.packet = build_packet(self.store, "spring-break", 1, 1, 0, len("A quiet room in the Ling house."))

    def test_ne015_test_retrieval_has_no_direct_luar_load_and_fails_closed(self):
        path = Path(__file__).resolve().parents[1] / "tools" / "test_retrieval.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "LuarIndex":
                self.fail("tools/test_retrieval.py must not load LuarIndex directly")
        unavailable = RetrievalSetup("unconfigured", "Reference policy unconfigured for test")
        with patch("prose_engine.reference_service.prepare_retrieval", return_value=unavailable) as prep:
            rc = test_retrieval.main(["--books", str(self.root), "coffee"])
        self.assertEqual(rc, 1)
        prep.assert_called_once_with(str(self.root), "luar", "local", purposes=("rank_local", "inspect_local"))

    def test_ne012_semantic_paraphrase_review_blocks_without_breaking_default_meaning(self):
        paraphrases = [
            "A man sired Haley.",
            "Haley was born to a father.",
            "Haley inherited his genes from her male parent.",
            "Her biological dad raised Haley.",
            "Haley stepped inside the hallway. Her biological dad called after her.",
        ]
        for text in paraphrases:
            with self.subTest(text=text):
                sem = assess_semantic_review(self.packet, text)
                self.assertEqual(sem["status"], "contradicted")
                self.assertEqual(sem["coverage"]["semantic_verifier"], "local_semantic_paraphrase_v1")
                self.assertTrue(validate_output(self.packet, text))
                law_res = enforce_standalone_world_laws(text, timeline_path=self.db_path)
                self.assertFalse(law_res["passed"])
                self.assertNotIn("Confidential sapphire blueprint", json.dumps(sem))

        # Quotation / joke contexts remain uncertain (not hard contradictions) and default meaning stays unchanged.
        rumor = assess_semantic_review(self.packet, 'Roger joked, "A man sired Haley."')
        self.assertEqual(rumor["status"], "uncertain")
        default_view = assess_meaning(self.packet, "A man sired Haley.")
        self.assertEqual(default_view["coverage"]["semantic_verifier"], "not_configured")

        scoped_val = execute_scoped(
            self.store,
            "validate",
            {
                "episode": "spring-break",
                "beat": 1,
                "revision": 1,
                "start": 0,
                "end": 12,
                "project": "project",
                "universe": "universe",
                "text": "A man sired Haley.",
            },
        )
        self.assertEqual(scoped_val["semantic_review"]["status"], "contradicted")
        self.assertTrue(scoped_val["issues"])

    def test_ne012_noir_timeline_env_workbench_and_editorial_dispatch(self):
        old_env = os.environ.get("NOIR_TIMELINE")
        os.environ["NOIR_TIMELINE"] = str(self.db_path)
        try:
            self.assertEqual(resolve_default_timeline(), self.db_path)
        finally:
            if old_env is None:
                os.environ.pop("NOIR_TIMELINE", None)
            else:
                os.environ["NOIR_TIMELINE"] = old_env

        scene_file = self.root / "scene.md"
        original_para = "A quiet evening in the Ling living room stretched past nine."
        scene_file.write_text(original_para + "\n", encoding="utf-8")

        provider = _StaticProvider("Haley was born to a father in the Ling living room.")
        bench = workbench.Workbench(
            scene_file,
            self.root / "wb_out",
            provider,
            use_retrieval=False,
            telemetry_dir=self.root / "telemetry",
            law_timeline=self.db_path,
            project_id="project",
            universe_id="universe",
            episode="spring-break",
            branch="main",
            beat=1,
        )
        res = bench.rewrite(0, 0.5)
        self.assertFalse(res["accepted"])
        self.assertTrue(any("world law:" in item for item in res["issues"]))

        rev_db = self.root / "revisions.sqlite"
        RevisionStore.create(rev_db, original_para, ())
        store = RevisionStore(rev_db)
        world = WorldState(rules=[], characters={}, banned=[])
        preview = editorial_dispatch(
            store,
            world,
            {
                "action": "preview",
                "base": 0,
                "expected": original_para,
                "replacement": "A man sired Haley before dinner.",
            },
            timeline_path=self.db_path,
        )
        self.assertEqual(preview["status"], "BLOCKED")
        self.assertTrue(any(i.get("code") == "world_law" for i in preview["new_issues"]))

    def test_ne013_craft_brief_includes_character_personality_and_pov_bounds(self):
        forms_path = self.root / "character-forms.sqlite"
        form_store = FormGraphStore(forms_path)
        g0 = form_store.read()
        port_id = next(
            f["port_id"]
            for j in g0["junctions"]
            if j["character_id"] == "francine"
            for f in j["forms"]
            if f["id"] == "francine"
        )
        g1 = form_store.change(
            {
                "action": "create_mind_link",
                "revision": g0["revision"],
                "kind": "digital_mind",
                "label": "Francine Base Mind",
                "port": port_id,
            }
        )
        node_id = next(
            f["link"]["node_id"]
            for j in g1["junctions"]
            if j["character_id"] == "francine"
            for f in j["forms"]
            if f["id"] == "francine"
        )
        form_store.change(
            {
                "action": "save_node_data",
                "revision": g1["revision"],
                "character": "francine",
                "node": f"data:{port_id}",
                "content": {"text_fields": {"personality": "Breezy suburban poise hiding sharp sarcasm."}},
            }
        )
        scoped_store = TimelineStore(self.db_path, project_id="project", universe_id="universe", form_graph_path=forms_path)
        profiles = CharacterProfileStore(scoped_store)
        junctions = form_store.junctions()
        profiles.save(
            "francine",
            "francine",
            node_id,
            "digital_mind",
            0,
            [
                {
                    "id": "p-1",
                    "category": "personality",
                    "text": "Deadpan protective mother with pristine pearl poise.",
                    "source_type": "universal_author",
                    "source_id": "author:francine-base",
                    "confidence": "author",
                }
            ],
            junctions,
        )
        res = run_craft_brief(
            scoped_store,
            {
                "action": "compile",
                "episode": "spring-break",
                "beat": 1,
                "revision": 1,
                "viewpoint": "francine",
                "lens_id": "irby",
            },
        )
        brief = res["brief"]
        self.assertEqual(res["action"], "compile")
        self.assertLessEqual(brief["byte_size"], 6144)
        self.assertIn("MIND DIRECTIVES:", brief["prompt"])
        self.assertIn("Deadpan protective mother", brief["prompt"])
        self.assertIn("Enforce POV francine", brief["prompt"])
        self.assertGreaterEqual(res["character_count"], 1)
        self.assertTrue(res["character_receipts"])
        self.assertNotIn("Confidential sapphire blueprint", brief["prompt"])

    def test_ne014_record_standalone_draft_and_cross_block_ui_assets(self):
        # 1) Unscoped standalone path writes durable generation receipt
        unscoped = record_standalone_draft(
            "Rewritten scene paragraph.",
            original_text="Original scene paragraph.",
            source_path=self.root / "draft.md",
            route="condition",
            provider_name="mock",
            out_dir=self.root / "out_unscoped",
        )
        self.assertFalse(unscoped["recorded_in_timeline"])
        self.assertEqual(unscoped["scope_status"], "unscoped-standalone")
        self.assertTrue(Path(unscoped["receipt_path"]).is_file())

        # 2) Timeline-connected standalone path records scope-aware DraftStore entry
        scoped = record_standalone_draft(
            "A dim room in the Ling house.",
            original_text="A quiet room in the Ling house.",
            source_path=self.root / "draft.md",
            route="condition",
            provider_name="mock",
            timeline_path=self.db_path,
            project_id="project",
            universe_id="universe",
            episode="spring-break",
            branch="main",
            beat=1,
        )
        self.assertTrue(scoped["recorded_in_timeline"])
        self.assertEqual(scoped["status"], "PROPOSED")
        saved = DraftStore(NotebookStore(self.store)).open("spring-break", "main", scoped["draft_id"])
        self.assertEqual(saved["text"], "A dim room in the Ling house.")

        # 3) Cross-block highlighter UI assets include live span metadata & card highlight class
        compose_js = (Path(__file__).resolve().parents[1] / "tools" / "assets" / "v2" / "compose.js").read_text(encoding="utf-8")
        compose_css = (Path(__file__).resolve().parents[1] / "tools" / "assets" / "v2" / "compose.css").read_text(encoding="utf-8")
        self.assertIn("v2-mask-span-meta", compose_js)
        self.assertIn("is-in-selection", compose_js)
        self.assertIn("blockIndices", compose_js)
        self.assertIn(".v2-mask-span-meta", compose_css)
        self.assertIn(".v2-block-card.is-in-selection", compose_css)


if __name__ == "__main__":
    unittest.main()
