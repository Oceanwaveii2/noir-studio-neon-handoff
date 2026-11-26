"""Offline tests for the closed-loop Gemini session controller driving Mean Girls/Spring Break & Tapped Out."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from prose_engine.gemini_driver import (
    control_candidate_output,
    drive_gemini_alternate_spring_break,
    drive_gemini_tapped_out_rewrite,
)
from story_graph.fx06_scene import PERFUME_LINE


class GeminiDriverTests(unittest.TestCase):
    def test_gemini_spring_alternate_self_control_repairs_bare_peter_and_canon(self):
        prompts_seen = []

        def fake_gemini(prompt: str) -> str:
            prompts_seen.append(prompt)
            if len(prompts_seen) == 1:
                # Deliberate violations: bare "Peter:", "husband Jeff" (anachronistic in Spring Break),
                # and missing "sandalwood" so the control loop must repair + retry once within budget!
                return (
                    "### SCENE 4: THE THREE LITTLE BITCHES\n"
                    "Rainee splits into three behind the door.\n"
                    "Rainee 1: Close the door on your husband Jeff.\n"
                    "Rainee 2: Rule stays.\n"
                    "Rainee 3: Light is dark.\n"
                    "Francine: Eyes on me.\n"
                    "Rainee became Peter.\n"
                    "Peter: Move.\n"
                    "Peter blasts Haley down the hall.\n"
                    "Then Peter destabilizes back into the same Three Little Bitches.\n"
                    "They release tuberose and orange.\n"
                    "Keys and lasagna sit on the tray.\n"
                )
            # Second turn fixes bare Peter + missing sandalwood; still leaves "husband Jeff"
            # so auto_correct_canon repairs it deterministically!
            return (
                "### SCENE 4: THE THREE LITTLE BITCHES\n"
                "Rainee splits into three behind the door.\n"
                "Rainee 1: Wait until your husband Jeff hears this.\n"
                "Rainee 2: Bathroom rules stand.\n"
                "Rainee 3: The fan switch is dead.\n"
                "Francine: Eyes here, all of you.\n"
                "Regular Francine brings them together, then Rainee becomes Rainee Peter Griffen.\n"
                "Francine laughs at her wife and asks for Nurse Franny.\n"
                "Rainee Peter Griffen: Nurse form granted.\n"
                "Nurse Franny steps back as Rainee Peter Griffen rips a huge fart blast sending Haley down the hall.\n"
                "Rainee Peter Griffen destabilizes back into the same Three Little Bitches.\n"
                "Together they unleash a second fart blast of tuberose, orange, and sandalwood that farts their bitch daughter away down the hall.\n"
                "Rainee 1: Floor cleared.\n"
                "Rainee 2: Nobody breaks ranks.\n"
                "Rainee 3: Four floor tiles past the door.\n"
                "Nurse Franny packs the clothes in a red overnight bag, leaves keys and lasagna trays with Haley, and pulls out in the sedan.\n"
            )

        with tempfile.TemporaryDirectory() as tmp:
            result = drive_gemini_alternate_spring_break(
                Path(tmp) / "spring",
                leaving_mode="clothes",
                session_handler=fake_gemini,
                max_calls=2,
                use_movie_dir=False,
            )
        self.assertEqual(result["status"], "PASSED")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["provider_calls"], 2)
        self.assertEqual(len(result["turns"]), 2)
        self.assertFalse(result["turns"][0]["passed"])
        self.assertTrue(result["turns"][1]["passed"])
        # Canon corrector deterministically repaired husband Jeff -> boyfriend Jeff on Gemini's output!
        self.assertIn("boyfriend Jeff", result["text"])
        self.assertNotIn("husband Jeff", result["text"])
        self.assertGreaterEqual(len(result["verdict"]["canon_corrections"]), 1)
        self.assertTrue(result["history_check"]["undone_restored_placeholder"])
        self.assertTrue(result["history_check"]["redone_matches_assembled"])
        self.assertTrue(result["history_check"]["haley_lock_preserved"])
        self.assertTrue(result["history_check"]["roger_suffix_preserved"])

    def test_gemini_tapped_out_rewrite_controls_output_and_updates_graph(self):
        def fake_gemini(_prompt: str) -> str:
            # Includes deliberate "Smith Kitchen" bleed so canon_corrector fixes it to "Ling Kitchen"
            # before Tapped Out character/transformation synthesis runs!
            return (
                "INT. SMITH KITCHEN STUDIO - DAY\n\n"
                "Francine: Keep the studio door locked.\n\n"
                "Haley: Checking the lights.\n\n"
                "Stella transforms into Big Tiddy Steve in her canary-yellow polo.\n\n"
                "STELLA (Big Tiddy Steve): The buttons popped again.\n\n"
                "STELLA (Big Tiddy Steve): Dialing the cube now.\n\n"
                "Stella shifts into Studio Overload Form.\n\n"
                "Holly: Holly Graham is running this scene.\n"
            )

        with tempfile.TemporaryDirectory() as tmp:
            result = drive_gemini_tapped_out_rewrite(
                Path(tmp) / "tapped",
                session_handler=fake_gemini,
                max_calls=2,
            )
        self.assertEqual(result["status"], "PASSED")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["provider_calls"], 1)
        self.assertIn("LING KITCHEN", result["text"].upper())
        syn = result["graph_result"]["synthesis"]
        self.assertIn("stella", syn["reused_characters"])
        self.assertIn("francine", syn["reused_characters"])
        self.assertEqual(syn["added_characters"], [{"character_id": "holly", "label": "Holly"}])
        self.assertTrue(any(f["character_id"] == "stella" and f["label"] == "Studio Overload Form" for f in syn["added_forms"]))
        self.assertEqual(result["graph_result"]["cook"]["stage2"]["unresolved_blocks"], 0)
        self.assertTrue(result["history_check"]["undo_restored_seed"])
        self.assertTrue(result["history_check"]["redo_restored_rewrite"])
        self.assertEqual(result["history_check"]["second_pass_added_characters"], [])
        self.assertIn("holly", result["history_check"]["second_pass_reused_characters"])

    def test_control_candidate_blocks_ai_cliche_and_strips_fences(self):
        v = control_candidate_output(
            "```markdown\nRainee let out a baritone trombone inside the Smith Kitchen.\n```",
            episode_id="spring-break",
        )
        self.assertFalse(v["passed"])
        self.assertIn("Ling Kitchen", v["text"])
        self.assertFalse(v["text"].startswith("```"))
        self.assertTrue(any("baritone trombone" in m.lower() or "cliche" in m.lower() for m in v["hard_issues"]))

    def test_full_story_named_splits_sade_becky_clarie_with_cook_and_scoped_validate(self):
        def fake_gemini(prompt: str) -> str:
            if "ONLY Scenes 1 to 3" in prompt:
                return (
                    "### SCENE 1: KITCHEN BRIEFING & THE ANCESTRAL MASSAGE\n"
                    "Francine Ling stands by her cherry-red wheeled bag beside three lasagna trays.\n"
                    "Francine: Three nights of lasagna, two nights of orange chicken, and Baba's ancestral farting.\n"
                    "Stella: Origami bows hold steady.\n"
                    "Haley: Let me check on Mom Two.\n\n"
                    "### SCENE 2: MASTER SUITE & THE SUDDEN COUP\n"
                    "Rainee cramps at her vanity and sprints toward the bathroom in puffs of French perfume.\n\n"
                    "### SCENE 3: THE DOUBLE COMMODE & THE TWO-CHAIR RULE\n"
                    "The toilet widens into a double-wide black lotus throne as jasmine mist rolls beneath the oak door.\n"
                    f"Haley: {PERFUME_LINE}\n"
                )
            if "ONLY Scene 7" in prompt:
                return (
                    "### SCENE 7: ROGER'S RUTGERS SPRING BREAK TAKEOVER\n"
                    "Roger: Take these backpacks to the freeway motel — they'll buy you jewelry!\n"
                    "Haley: No chance, Roger.\n"
                    "Stella: Hands off the lasagna trays, Roger.\n"
                    "Roger flares his purple cape as the Rutgers Spring Break charter bus roars up.\n"
                    "Frat Guy: Clear bags!\n"
                )
            return (
                "### SCENE 4: THE THREE LITTLE BITCHES\n"
                "Rainee splits into three behind the door: Rainee 1 (Rainee Sade), Rainee 2 (Rainee Becky), and Rainee 3 (Rainee Clarie).\n"
                "Rainee Sade: Verdict first — nobody touches that fan.\n"
                "Rainee Becky: Follow house rules before you open your mouth, Haley.\n"
                "Rainee Clarie: Your left sneaker is untied.\n"
                "Francine: Eyes here, all three of you.\n"
                "Regular Francine brings them back together, then Rainee swells into Rainee Peter Griffen.\n"
                "Francine laughs at her spouse and asks for Nurse Franny.\n"
                "Rainee Peter Griffen: Stand clear — Nurse Franny has arrived!\n"
                "Nurse Franny steps aside as Rainee Peter Griffen blasts Haley down the hall with fart blast number one.\n"
                "Rainee Peter Griffen immediately destabilizes back into Rainee Sade, Rainee Becky, and Rainee Clarie.\n"
                "Together they rip a second fart blast smelling of tuberose, orange, and sandalwood that farts their bitch daughter Haley farther down the hall.\n"
                "Rainee Sade: Nobody argues after two frames.\n"
                "Rainee Becky: Loyalty means admitting you slipped.\n"
                "Rainee Clarie: She hit the third coat hook.\n"
                "Haley: Keep your three perfume counters.\n\n"
                "### SCENE 5A: THE CLOTHES\n"
                "Nurse Franny: Pack your travel outfits in the red overnight bag; Haley holds the keys and three trays of lasagna.\n"
                "Rainee Sade: Wrap dress first.\n"
                "Rainee Becky: Silk follows evening protocol.\n"
                "Rainee Clarie: The sleeve has mascara.\n\n"
                "### SCENE 6: THE RED SEDAN\n"
                "Nurse Franny drives Rainee Sade, Rainee Becky, and Rainee Clarie away in the red sedan.\n"
            )

        with tempfile.TemporaryDirectory() as tmp:
            story_out = Path(tmp) / "out_story.md"
            result = drive_gemini_alternate_spring_break(
                Path(tmp) / "spring-full",
                leaving_mode="clothes",
                session_handler=fake_gemini,
                max_calls=2,
                use_movie_dir=False,
                full_story=True,
                require_named_splits=True,
                out_story=story_out,
            )
            self.assertEqual(result["status"], "PASSED")
            self.assertTrue(result["accepted"])
            self.assertEqual(result["graph_result"]["cook"]["stage2"]["unresolved_blocks"], 0)
            self.assertIsNotNone(result["scoped_validation"])
            self.assertTrue(story_out.is_file())
            txt = story_out.read_text(encoding="utf-8")
            self.assertIn("Rainee Sade:", txt)
            self.assertIn("Rainee Becky:", txt)
            self.assertIn("Rainee Clarie:", txt)
            self.assertIn("SCENE 7:", txt)

    def test_episode_commands_intake_launch_from_drop_or_prompt(self):
        import base64
        from prose_engine.episode_commands import EpisodeCommands
        from story_graph.episode_timeline import TimelineStore
        from story_graph.form_graph_store import FormGraphStore

        class FakeProvider:
            def generate_rewrite(self, _req, _prompt):
                return (
                    "### SCENE 1: STUDIO WARMUP\n"
                    "Francine Ling checks the cue sheet beside Holly.\n\n"
                    "Francine: Keep the studio lights steady.\n\n"
                    "Stella transforms into Big Tiddy Steve in her canary-yellow polo.\n\n"
                    "STELLA (Big Tiddy Steve): Levels locked!\n\n"
                    "Holly: Holly Graham is starting take one.\n"
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tl = TimelineStore(root / "tl.sqlite")
            forms = FormGraphStore(root / "forms.sqlite")
            tl.add_starter_cards()
            cmds = EpisodeCommands(tl, form_graph=forms, provider_factory=FakeProvider)
            doc_bytes = b"INT. STUDIO - DAY\n\nFrancine and Stella wait beside the console.\n"
            doc = {"name": "tapped_seed.txt", "base64": base64.b64encode(doc_bytes).decode()}
            prev = cmds.execute("intake.preview", {"document": doc})
            created = cmds.execute("intake.create", {
                "title": "Dragged Tapped Out Seed",
                "branch": "main",
                "after": "end",
                "prompt": "Rewrite Tapped Out with Holly and Stella -> Big Tiddy Steve.",
                "provider": "gemini-session",
                "document": doc,
                "file_sha256": prev["source"]["sha256"],
                "text_sha256": prev["source"]["text_sha256"],
                "request_id": "drop-test-1",
            })
            launched = cmds.execute("intake.launch", {
                "episode": created["episode"],
                "prompt": "Rewrite Tapped Out with Holly and Stella -> Big Tiddy Steve.",
                "provider": "gemini-session",
                "workflow_mode": "auto",
                "references": "none",
            })
            self.assertEqual(launched["status"], "PASSED")
            self.assertTrue(launched["accepted"])
            self.assertEqual(launched["workflow_mode"], "tapped-out")
            self.assertIn("holly", launched["graph_result"]["synthesis"]["reused_characters"] + [c["character_id"] for c in launched["graph_result"]["synthesis"]["added_characters"]])
            self.assertEqual(launched["graph_result"]["cook"]["stage2"]["unresolved_blocks"], 0)
            self.assertTrue(launched["system_steps"])
            self.assertTrue(launched["ai_summary"])

            hist = cmds.execute("intake.history", {"episode": created["episode"]})
            self.assertEqual(len(hist["entries"]), 1)

            follow_up = cmds.execute("intake.launch", {
                "episode": created["episode"],
                "prompt": "Keep Holly sharp on deadlines while Stella checks cube metrics.",
                "attachment_name": "note.txt",
                "attachment_text": "Note: Holly demands strict cube turnaround.",
                "provider": "gemini-session",
                "workflow_mode": "tapped-out",
                "references": "none",
            })
            self.assertTrue(follow_up["accepted"])
            self.assertEqual(len(follow_up["director_history"]), 2)
            self.assertEqual(follow_up["director_history"][1]["attachment"], "note.txt")


if __name__ == "__main__":
    unittest.main()
