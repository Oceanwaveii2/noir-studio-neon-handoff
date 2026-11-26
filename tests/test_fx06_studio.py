"""Scope and preservation tests for the Studio split pilot, without a model call."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from prose_engine.episode_commands import EpisodeCommands
from prose_engine.notebook import NotebookStore
from prose_engine.scoped_service import execute_scoped
from story_graph import fx06_scene as scene
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore
from story_graph.source_imports import junctions
from tools.fx06_studio import prepare


CANDIDATE = (
    "Rainee 1: I decide when that bathroom is clear.\n"
    "Action: She holds up a finger.\n"
    "Rainee 2: Everyone knows perfume in the hall counts.\n"
    "Action: She nods to the first Rainee.\n"
    "Rainee 3: The fan light is dark. Ask the fan.\n"
    "Action: She points at the fan."
)


class Fx06StudioTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        evidence = {f"early-{i}": {"id": f"early-{i}"} for i in range(3)}
        actors = [dict(form_id=form, speaker=speaker, role=role, mind_label=role,
                       tendencies=[{"when": "challenged", "try": tactic, "evidence": [f"early-{i}"]}],
                       constraint="Stay inside the scene.")
                  for i, (form, speaker, role, tactic) in enumerate(zip(
                      scene.CAST, scene.SPEAKERS, scene.ROLES,
                      ("Claim the floor", "Back an ally", "Point to a literal detail")))]
        fake_bundle = {"actors": actors, "evidence": evidence, "relationships": [],
                       "timing": [{"id": "timing-only", "hint": "Pause before the reaction."}],
                       "cutaway": {"window_ms": [117400, 117500],
                                   "split": "invert_three_to_one_shape", "rejoin": "reuse_three_to_one_shape"},
                       "manifests": {}}
        with patch("tools.fx06_studio.scene.load_bundle", return_value=fake_bundle):
            receipt = prepare(root / "workspace", root)
        self.timeline = TimelineStore(Path(receipt["timeline"]))
        with self.timeline._connect() as connection:
            self.graph = FormGraphStore(Path(receipt["forms"]), imported=junctions(connection, {}))
        self.notebook = NotebookStore(self.timeline)
        self.commands = EpisodeCommands(self.timeline, junctions=self.graph.junctions)
        self.scope = receipt["scope"]
        self.roast = {**self.scope, **{k: receipt["roast"][k] for k in ("beat", "start", "end")}}

    def scoped(self, action, request, **kwargs):
        return execute_scoped(self.timeline, action, request, junctions=self.graph.junctions, **kwargs)

    def test_scene_phases_do_not_write_state_and_can_only_use_original_scope(self):
        saved = self.notebook.open(scene.EPISODE)
        view = self.commands.execute("fx06.open", self.scope)
        states = [p["state"] for p in view["phases"]]
        self.assertEqual([s["root_form"] for s in states], ["rainee", "split", "rainee", scene.PETER])
        self.assertEqual([len(s["active_cast"]) for s in states], [0, 3, 0, 0])
        self.assertEqual([a["form_id"] for a in states[1]["active_cast"]], list(scene.CAST))
        self.assertEqual(len({a["node_id"] for a in states[1]["active_cast"]}), 3)
        self.assertEqual([s["override"]["operator"] for s in states[1:3]],
                         ["invert_three_to_one_shape", "reuse_three_to_one_shape"])
        self.assertTrue(all(s["memory"] is None and not s["writes_canon"] for s in states))
        self.assertIsNone(view["draft"])
        self.assertEqual(self.notebook.open(scene.EPISODE), saved)
        with self.assertRaisesRegex(ValueError, "original branch"):
            self.commands.execute("fx06.open", {**self.scope, "branch": "main"})
        with self.assertRaisesRegex(ValueError, "revision is stale"):
            self.commands.execute("fx06.open", {**self.scope, "revision": 0})
        with self.assertRaisesRegex(ValueError, "its own beat"):
            self.scoped("context", {**self.roast, "beat": 3})
        with self.assertRaisesRegex(ValueError, "pilot workspace"):
            self.commands.execute("fx06.open", {**self.scope, "episode": "spring-break"})

    def test_unplugged_mind_and_ordinary_form_bindings_fail_closed(self):
        self.timeline.add_event("preview-test", scene.EPISODE, 2, "A draft note.")
        for form in (scene.CAST[0], scene.PETER):
            with self.assertRaisesRegex(ValueError, "controlled by its authored scene"):
                self.timeline.bind_form_event(scene.EPISODE, "preview-test", "rainee", form,
                                              "active", self.graph.junctions())
        self.graph.change({"action": "set_link", "port": f"character:rainee:form:{scene.CAST[0]}",
                           "node_id": None, "revision": self.graph.read()["revision"]})
        with self.assertRaisesRegex(ValueError, "three original Digital Mind links"):
            self.scoped("context", self.roast)

    def test_preview_and_candidate_validation_preserve_the_notebook(self):
        saved = self.notebook.open(scene.EPISODE)
        scope = {**self.roast, "provider": "codex-session", "references": "none"}
        broken = CANDIDATE.replace("Rainee 2:", "Rainee 1:")
        issues = self.scoped("validate", {**scope, "text": broken})["issues"]
        self.assertTrue(any("missing, duplicated or out of order" in i.get("reason", "") for i in issues))
        prompts = []

        class Writer:
            def generate_rewrite(self, _request, prompt):
                prompts.append(prompt)
                return CANDIDATE

        preview = self.scoped("rhythm-preview", scope, provider_factory=Writer)
        self.assertFalse(preview["generation_started"])
        self.assertFalse(prompts)
        result = self.scoped("generate", {**scope, "request_id": "fx06-test",
                                         "rhythm_plan_id": preview["rhythm_guidance"]["id"]},
                             provider_factory=Writer)
        self.assertEqual(len(prompts), 1)
        self.assertIn("FX06 ACTIVE SCENE CAST", prompts[0])
        self.assertTrue(all(role in prompts[0] for role in scene.ROLES))
        self.assertEqual(result["status"], "PROPOSED")
        readback = self.commands.execute("fx06.open", self.scope)
        self.assertEqual(readback["protected_line"], scene.PERFUME_LINE)
        self.assertEqual(readback["draft"]["id"], result["draft_id"])
        self.assertEqual(readback["draft"]["text"], CANDIDATE)
        self.assertEqual(self.notebook.open(scene.EPISODE), saved)
