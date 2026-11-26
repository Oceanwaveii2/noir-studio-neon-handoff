"""Phase 5 Anti-Sabotage Regression Suite for Noir's Unified Prose Architecture."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prose_engine.episode_commands import EpisodeCommands
from prose_engine.gemini_driver import plan_episode_from_intake
from prose_engine.mean_girls_minds import (
    attach_mean_girls_minds_to_form_graph,
    build_three_little_bitches_minds,
)
from prose_engine.notebook import NotebookStore, digest
from prose_engine.providers.composer_bridge import _timeout_runner
from prose_engine.rhythm_guidance import compile_guidance
from prose_engine.scoped_pipeline import build_packet, prompt_for
from prose_engine.spring_alternate import (
    PERFUME_LINE,
    build_alternate_spring_packet,
    validate_alternate_spring_candidate,
)
from prose_engine.voice.slop_critic import SlopCritic
from story_graph.character_forms import AFM_JUNCTIONS
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore


class TestUnifiedProseArchitecture(unittest.TestCase):
    def test_slop_critic_density_scales_for_full_length_manuscripts(self):
        critic = SlopCritic(use_saved_model=False)
        # 2,600+ word clean narrative with varied sentences and occasional '-ing' clauses must NOT be hard-blocked by raw sum.
        paragraphs = [
            (
                "Francine checked the brass latch beside the pantry door. She stacked two foil trays on the granite counter, "
                "counting out napkins before the kettle whistled behind her. Haley leaned on the doorframe with her duffel "
                "strap twisted over one shoulder. Outside, a delivery truck rattled past the cul-de-sac hedges."
            ),
            (
                "Down the hall, a floorboard gave a sharp creak under Rainee's slipper. Red silk brushed the doorframe. "
                "She paused at the mirror and flicked a loose strand behind her ear. Nothing in the house stayed quiet for long."
            ),
            (
                "Stella folded a square of bright yellow paper along the tabletop edge. Her thumb pressed the crease flat. "
                "Three mugs sat near the toaster, still warm from the first pot. Morning light cut across the tile in pale bars."
            ),
        ]
        long_chapter = "\n\n".join(paragraphs[i % len(paragraphs)] for i in range(60))
        self.assertGreater(len(long_chapter.split()), 2400)
        res = critic.critique(long_chapter)
        self.assertTrue(res.passed, f"Full-length clean chapter falsely blocked: {res.hard_blocks}")
        self.assertLess(res.slop_score, 65.0)

        # Dense short slop must still be blocked.
        dense_slop = (
            "Haley felt the weight of the room, shimmering with pneumatic precision as a baritone trombone "
            "shook her, reminding her of a tapestry."
        )
        bad = critic.critique(dense_slop)
        self.assertFalse(bad.passed)
        self.assertTrue(bad.hard_blocks)

    def test_no_forced_cadence_erasure_in_entrypoints(self):
        root = Path(__file__).resolve().parents[1]
        for rel in (
            "prose_engine/writing_runs.py",
            "prose_engine/episode_commands.py",
            "prose_engine/scene_bridges.py",
            "prose_engine/service_daemon.py",
        ):
            src = (root / rel).read_text(encoding="utf-8")
            self.assertNotIn("'reference_delivery':'cadence'", src, f"{rel} still hardcodes cadence!")
            self.assertNotIn("'reference_delivery': 'cadence'", src, f"{rel} still hardcodes cadence!")

    def test_expand_mode_delivers_real_book_excerpts_into_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TimelineStore(Path(tmp) / "timeline.sqlite")
            ep = "expand-test"
            src = 'FRANCINE: "Leave the keys."\n\nHaley drops the keyring onto the counter.'
            store.create_episode(ep, "Expand Test", "main", 10)
            store.save(ep, 0, script=src, source_name="expand.txt")
            book = NotebookStore(store)
            st = book.open(ep)
            book.save(ep, st["revision"], 1, st["blocks"], 25, [])
            packet = build_packet(store, ep, 0, 1, 0, len(src), junctions=AFM_JUNCTIONS)

            excerpts = (
                "The chrome toaster threw back a warped strip of kitchen light across her knuckles.",
                "She flicked the strap off her shoulder and let the canvas bag thud against the baseboard.",
            )
            receipts = [
                {"passage_id": "p1", "source_id": "book_a", "excerpt_sha256": "a" * 64, "hybrid_backend": "style"},
                {"passage_id": "p2", "source_id": "book_b", "excerpt_sha256": "b" * 64, "hybrid_backend": "luar"},
            ]
            guidance = compile_guidance(
                packet,
                "comedy",
                reference_features={"sample_count": 2, "mean_sentence_words": 14.0, "sentence_length_variation": 4.2},
                reference_receipts=receipts,
                craft_mode="expand",
            )
            prompt = prompt_for(
                packet,
                references=excerpts,
                scene_function="comedy",
                reference_features={"sample_count": 2},
                reference_receipts=receipts,
                rhythm_guidance=guidance,
            )
            self.assertIn("EXPAND & ENRICH UNLOCKED PROSE", prompt)
            self.assertIn("chrome toaster threw back a warped strip", prompt)
            self.assertIn("canvas bag thud against the baseboard", prompt)

    def test_spring_alternate_causal_state_machine_blocks_regressions(self):
        minds = build_three_little_bitches_minds(include_movie_dir=False)
        prefix = f"INT. HALL - MORNING\nHaley: {PERFUME_LINE}\n\n"
        suffix = "\n\n### SCENE 7: ROGER RUTGERS TAKEOVER\nRoger steps out.\n"
        pkt = build_alternate_spring_packet(
            prefix,
            "[EDITABLE]",
            suffix,
            minds,
            leaving_mode="clothes",
            full_story=False,
            require_named_splits=True,
        )
        pkt["min_words"] = 120

        # 1. Nurse Franny summoned as separate person + duplicate locked line + post-destabilize Peter cue + short text
        broken = (
            f"Haley: {PERFUME_LINE}\n"
            'Francine: "Nurse Franny, get up here right now!"\n'
            "Rainee Peter Griffen: Hehehe!\n"
            "Rainee Peter Griffen destabilizes back into three.\n"
            "Rainee Peter Griffen: Wait, I am still talking.\n"
            "Rainee Sade: Cute. Tuberose.\n"
            "Rainee Becky: Orange.\n"
            "Rainee Clarie: Sandalwood. Fart blast. Keys and lasagna and overnight bag.\n"
            f"Haley: {PERFUME_LINE}\n"
        )
        res = validate_alternate_spring_candidate(broken, pkt)
        joined_issues = "\n".join(res["issues"])
        self.assertIn("Causal order violation", joined_issues)
        self.assertIn("Morph state violation", joined_issues)
        self.assertIn("Morph identity violation", joined_issues)
        self.assertIn("Duplicate locked line violation", joined_issues)
        self.assertIn("Prose condensation violation", joined_issues)

    def test_intake_plan_is_read_only_and_preserves_notebook_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tl = TimelineStore(root / "timeline.sqlite")
            forms = FormGraphStore(root / "forms.sqlite")
            ep_id = "plan-ep"
            src = f"### SCENE 3\nHaley: {PERFUME_LINE}\n\n### SCENE 4\nRainee splits into Rainee Sade, Rainee Becky, and Rainee Clarie."
            tl.create_episode(ep_id, "Plan Ep", "main", 10)
            tl.save(ep_id, 0, script=src, source_name="plan.md")
            nb = NotebookStore(tl)
            st = nb.open(ep_id)
            lock_start = src.index(PERFUME_LINE)
            lock_end = lock_start + len(PERFUME_LINE)
            st = nb.save(
                ep_id,
                st["revision"],
                st["timeline_revision"],
                st["blocks"],
                25,
                [{"id": "lock-1", "start": lock_start, "end": lock_end, "value": 100, "hard": True, "sha256": digest(PERFUME_LINE)}],
            )
            before_rev = st["revision"]

            cmds = EpisodeCommands(tl, form_graph=forms)
            planned = cmds.execute(
                "intake.plan",
                {
                    "episode": ep_id,
                    "prompt": "Expand Scene 4 with Rainee Sade, Rainee Becky, and Rainee Clarie.",
                    "references": "none",
                },
            )
            self.assertEqual(planned["status"], "PLANNED")
            self.assertTrue(planned["read_only"])
            self.assertEqual(len(planned["protected_locks"]), 1)
            self.assertEqual(nb.existing(ep_id)["revision"], before_rev)

    def test_composer_bridge_timeout_runner_overrides_90s_ceiling(self):
        captured = {}

        def fake_run(args, *pargs, **kwargs):
            captured["args"] = args
            captured["timeout"] = kwargs.get("timeout")
            return "OK"

        with patch.dict(os.environ, {"NOIR_GEMINI_TIMEOUT": "210"}), patch("subprocess.run", side_effect=fake_run):
            runner = _timeout_runner()
            out = runner(["agy.exe", "--print-timeout", "90s", "--model", "gemini-3.8-flash-medium"], timeout=100)
        self.assertEqual(out, "OK")
        self.assertIn("210s", captured["args"])
        self.assertNotIn("90s", captured["args"])
        self.assertEqual(captured["timeout"], 225)

    def test_no_paranoid_reference_copy_hard_blocks_in_pipeline(self):
        root = Path(__file__).resolve().parents[1]
        scoped_src = (root / "prose_engine/scoped_pipeline.py").read_text(encoding="utf-8")
        self.assertNotIn("reference_copies(", scoped_src)
        self.assertNotIn("Untrusted reference data", scoped_src)
        voice_pipe = (root / "prose_engine/voice/pipeline.py").read_text(encoding="utf-8")
        self.assertNotIn("copies_dropped", voice_pipe)
        self.assertNotIn("reference_copies(", voice_pipe)

    def test_direct_gemini_provider_and_active_cast_law_filter(self):
        from prose_engine.providers.gemini_direct import direct_api_available, generate_direct
        from story_graph.typed_laws import filter_laws_by_active_cast

        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
            if not os.environ.get("GOOGLE_API_KEY"):
                self.assertFalse(direct_api_available())

        fake_resp = b'{"candidates":[{"content":{"parts":[{"text":"Vivid scene line."}]}}]}'

        class FakeHTTP:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return fake_resp

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
            "prose_engine.providers.gemini_direct.urlopen", return_value=FakeHTTP()
        ):
            self.assertTrue(direct_api_available())
            self.assertEqual(generate_direct("Write scene"), "Vivid scene line.")

        laws = [
            {"id": "l1", "name": "Rainee Female", "statement": "Rainee forms are always female.", "enabled": True},
            {"id": "l2", "name": "Roger Space", "statement": "Roger hides in the attic.", "enabled": True},
            {"id": "l3", "name": "Global Ling", "statement": "Ling family only.", "enabled": True, "scope": "global"},
        ]
        filtered = filter_laws_by_active_cast(laws, ["rainee", "francine"])
        self.assertEqual([x["id"] for x in filtered], ["l1", "l3"])

    def test_peter_griffin_hub_and_downstairs_causal_sequence(self):
        scent_rules = {
            "rules": [
                {"form": "rainee-split-1", "scent": "tuberose", "perfume": "Gucci Bloom"},
                {"form": "rainee-split-2", "scent": "orange", "perfume": "Chanel Coco"},
                {"form": "rainee-split-3", "scent": "sandalwood", "perfume": "Le Labo Santal 33"},
            ]
        }
        minds = build_three_little_bitches_minds(scent_rules=scent_rules, include_movie_dir=False)
        with tempfile.TemporaryDirectory() as tmp:
            forms = FormGraphStore(Path(tmp) / "forms.sqlite")
            receipt = attach_mean_girls_minds_to_form_graph(forms, minds)
            self.assertIsNotNone(receipt.get("peter_node"))
            self.assertEqual(receipt["peter_node"]["form_id"], "peter_griffin_celestial_variant")
            fg = forms.read()
            rainee_j = next(j for j in fg["junctions"] if j["character_id"] == "rainee")
            peter_form = next(f for f in rainee_j["forms"] if f["id"] == "peter_griffin_celestial_variant")
            self.assertIsNotNone(peter_form.get("link"))
            peter_data = rainee_j["node_data"][receipt["peter_node"]["data_node_id"]]
            self.assertEqual(peter_data["structured_data"]["source"], "mean-girls-2004")

            pkt = build_alternate_spring_packet(
                f"### SCENE 3\nHaley: {PERFUME_LINE}\n\n",
                "[EDITABLE]",
                "\n\n### SCENE 7\nRoger waves.\n",
                minds,
                form_store=forms,
                leaving_mode="clothes",
                sequence_mode="downstairs_peter_split",
                require_named_splits=True,
            )
            self.assertIn("Peter Griffin Transformation Node", pkt["writer_brief"])

        good_downstairs = (
            "### SCENE 4: DOWNSTAIRS SPLIT\n"
            "Right after the bathroom scene, Rainee comes downstairs, farts, and splits.\n"
            "Rainee 1 (Rainee Sade): You look tragic.\n"
            "Rainee 2 (Rainee Becky): Follow the rules.\n"
            "Rainee 3 (Rainee Clarie): That headband was four dollars.\n"
            "Francine: Come back together right now, Rainee!\n"
            "Rainee recombines and transforms into Rainee Peter Griffen.\n"
            "Rainee Peter Griffen: Nye-hehehe! Stand back!\n"
            "A huge fart blast from Rainee Peter Griffen blows Haley across the living room.\n"
            "Francine laughs and asks for a nurse costume; Rainee Peter Griffen zaps her with nanites.\n"
            "Nurse Franny: Nurse Franny is here!\n"
            "Rainee Peter Griffen destabilizes from another fart back into Rainee 1 (Rainee Sade), Rainee 2 (Rainee Becky), and Rainee 3 (Rainee Clarie).\n"
            "Their second fart blast of tuberose, orange, and sandalwood blows Haley around the hallway.\n"
            "Rainee 1 (Rainee Sade): Pack the red overnight bag.\n"
            "Rainee 2 (Rainee Becky): Bring the house keys and lasagna trays.\n"
            "Rainee 3 (Rainee Clarie): Three trays total.\n"
        )
        ok = validate_alternate_spring_candidate(good_downstairs, pkt)
        self.assertTrue(ok["valid"], ok["issues"])

        bad_nurse_early = good_downstairs.replace(
            "Francine laughs and asks for a nurse costume; Rainee Peter Griffen zaps her with nanites.\nNurse Franny: Nurse Franny is here!\n",
            "",
        ).replace(
            "Rainee Peter Griffen: Nye-hehehe! Stand back!\n",
            "Nurse Franny: Nurse Franny is here before Peter farts!\nRainee Peter Griffen: Nye-hehehe! Stand back!\n",
        )
        bad = validate_alternate_spring_candidate(bad_nurse_early, pkt)
        self.assertFalse(bad["valid"])
        self.assertTrue(any("Nurse Franny" in msg for msg in bad["issues"]))


if __name__ == "__main__":
    unittest.main()
