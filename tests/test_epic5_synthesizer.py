"""Epic 5 verification: <6 KB CraftBrief, SlopCritic, BestOfN ranking, and Studio /api/craft-brief."""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from prose_engine.notebook import NotebookStore, digest
from prose_engine.scoped_pipeline import build_packet
from prose_engine.voice.slop_critic import SlopCritic
from prose_engine.voice.synthesizer import (
    DeNovoSynthesizer,
    DramaticBeat,
    MAX_CRAFT_BRIEF_BYTES,
    compile_craft_brief,
    extract_dialogue_skeleton,
)
from story_graph.character_forms import AFM_JUNCTIONS
from story_graph.episode_timeline import TimelineStore
from story_graph.world_laws import WorldLawStore
from tools import studio_ui


def _post_json(url: str, body: dict, origin: str):
    req = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Origin": origin},
        method="POST",
    )
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


class TestEpic5Synthesizer(unittest.TestCase):
    def test_craft_brief_respects_6kb_budget_and_multi_format_skeleton(self):
        script = (
            "INT. LING KITCHEN - MORNING\n"
            'FRANCINE: "Leave the suitcase by the door."\n'
            'HALEY: (glancing up) "Coffee first."\n'
        )
        skel = extract_dialogue_skeleton(script)
        self.assertEqual([d.speaker for d in skel], ["FRANCINE", "HALEY"])
        self.assertEqual(skel[0].text, "Leave the suitcase by the door.")
        self.assertEqual(skel[1].parenthetical, "glancing up")

        beats = [DramaticBeat(f"b{i}", f"Beat {i}: " + ("kettle steam curls across counter " * 8)) for i in range(1, 7)]
        brief = compile_craft_brief(
            "INT. LING KITCHEN - MORNING",
            beats,
            skel,
            lens_id="irby",
            viewpoint="haley",
            world_laws=["Francine is a Ling; never married Stan Smith." for _ in range(10)],
            mind_directives=["Haley stays laconic under pressure." for _ in range(10)],
            epistemic_withheld=["WITHHOLD garage pin from Haley." for _ in range(10)],
            craft_cues=["Keep sentences concrete and unpadded." for _ in range(10)],
            seed=7,
        )
        self.assertLessEqual(brief.byte_size, MAX_CRAFT_BRIEF_BYTES)
        self.assertEqual(brief.byte_size, len(brief.prompt.encode("utf-8")))
        self.assertIn("Leave the suitcase by the door.", brief.prompt)
        self.assertIn("Coffee first.", brief.prompt)

        tight = compile_craft_brief(
            "INT. LING KITCHEN - MORNING",
            beats,
            skel,
            world_laws=["Rule " + str(i) for i in range(12)],
            craft_cues=["Cue " + str(i) for i in range(12)],
            max_bytes=768,
            seed=7,
        )
        self.assertLessEqual(tight.byte_size, 768)
        self.assertTrue(tight.trimmed_sections)

    def test_slop_critic_blocks_cliches_exempts_negation_and_quotes(self):
        critic = SlopCritic(use_saved_model=False)

        clean = critic.critique("Haley set the chipped mug down beside the kettle. Steam cleared from the tile.")
        self.assertTrue(clean.passed)
        self.assertEqual(clean.slop_score, 0.0)
        self.assertEqual(clean.hard_blocks, [])

        sloppy = critic.critique(
            "Haley felt the weight of the room, shimmering as a baritone trombone shook her with pneumatic precision, "
            "while something shifted and reminded her of a tapestry."
        )
        self.assertFalse(sloppy.passed)
        self.assertGreater(sloppy.slop_score, 0.0)
        self.assertTrue(sloppy.hard_blocks)

        negation_ok = critic.critique(
            "Francine never married Stan Smith and stayed a Ling in the kitchen. "
            'Haley laughed. "Sounded like a baritone trombone out there."'
        )
        self.assertTrue(negation_ok.passed, negation_ok.hard_blocks)

    def test_denovo_synthesizer_best_of_n_neurosymbolic_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "timeline.sqlite"
            store = TimelineStore(db_path)
            ep = "synth-ep"
            src = (
                "FRANCINE: \"Leave the bags by the door.\"\n\n"
                "Haley pours dark roast into a chipped mug.\n\n"
                "HALEY: \"Keys are on the hook.\""
            )
            store.create_episode(ep, "Synth Ep", "main", 10)
            store.save(ep, 0, script=src, source_name="synth.txt")
            book = NotebookStore(store)
            st = book.open(ep)
            book.save(ep, st["revision"], 1, st["blocks"], 25, [])
            wls = WorldLawStore(store)
            cur = wls.open()
            wls.save(cur["revision"], [
                *cur["laws"],
                {"id": "no-smith", "name": "No Smith", "statement": "Never Francine Smith.", "enabled": True, "matcher": "literal", "phrases": ["Francine Smith"]},
            ])
            packet = build_packet(store, ep, 0, 1, 0, len(src), junctions=AFM_JUNCTIONS)

            skeleton = extract_dialogue_skeleton(src)
            beats = [DramaticBeat("b1", "Francine drops her overnight bag; Haley pours black coffee.")]
            critic = SlopCritic(use_saved_model=False)
            synth = DeNovoSynthesizer("irby", critic=critic)

            outputs = [
                # 0: missing dialogue line
                'FRANCINE: "Leave the bags by the door." Haley stirred sugar.',
                # 1: blacklisted cliche
                'FRANCINE: "Leave the bags by the door." A baritone trombone rattled the vent. HALEY: "Keys are on the hook."',
                # 2: world-law conflict (Francine Smith)
                'FRANCINE: "Leave the bags by the door." Francine Smith wiped the mug. HALEY: "Keys are on the hook."',
                # 3: clean winner with fresh phrasing
                'Francine dropped her canvas duffel beside the doorframe. "Leave the bags by the door." Black roast filled the stoneware cup before steam curled toward the ceiling. Haley tapped the brass keyring twice. "Keys are on the hook."',
            ]
            res = synth.synthesize_best_of_n(
                lambda _prompt: outputs.pop(0),
                "INT. LING KITCHEN - MORNING",
                beats,
                skeleton,
                n=4,
                reference_text=src,
                packet=packet,
                seeds=[11, 22, 33, 44],
            )
            self.assertEqual(res["status"], "PROPOSED")
            self.assertLessEqual(res["brief"]["byte_size"], MAX_CRAFT_BRIEF_BYTES)
            self.assertEqual(len(res["rejected"]), 3)
            self.assertIn("brass keyring", res["winner"]["text"])

    def test_studio_craft_brief_http_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "timeline.sqlite"
            store = TimelineStore(db_path)
            ep = "brief-ep"
            src = 'FRANCINE: "Stay sharp."\n\nHaley locked the back latch.'
            store.create_episode(ep, "Brief Ep", "main", 10)
            store.save(ep, 0, script=src, source_name="brief.txt")
            book = NotebookStore(store)
            st = book.open(ep)
            book.save(ep, st["revision"], 1, st["blocks"], 25, [])

            studio_ui.StudioRequestHandler.review_store_path = None
            studio_ui.StudioRequestHandler.novel_path = studio_ui.DEFAULT_NOVEL
            server = ThreadingHTTPServer(("127.0.0.1", 0), studio_ui.StudioRequestHandler)
            server.timeline_path = db_path
            server.form_graph = studio_ui.FormGraphStore(root / "forms.sqlite", studio_ui.form_targets())
            server.books_dir = root
            server.images_dir = root
            server.timeline_only = True
            server.test_writer_factory = None
            server.initial_episode = ep
            port = server.server_port
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                origin = f"http://127.0.0.1:{port}"
                st_bad, _ = _post_json(f"{origin}/api/craft-brief", {"action": "compile", "episode": ep}, "http://evil.example")
                self.assertEqual(st_bad, 403)

                st_comp, res_comp = _post_json(f"{origin}/api/craft-brief", {"action": "compile", "episode": ep}, origin)
                self.assertEqual(st_comp, 200)
                self.assertLessEqual(res_comp["brief"]["byte_size"], MAX_CRAFT_BRIEF_BYTES)
                self.assertEqual(res_comp["skeleton_count"], 1)

                st_crit, res_crit = _post_json(
                    f"{origin}/api/craft-brief",
                    {"action": "critique", "use_saved_model": False, "text": "Cold water hit the kettle with a pneumatic hiss."},
                    origin,
                )
                self.assertEqual(st_crit, 200)
                self.assertFalse(res_crit["passed"])

                st_rank, res_rank = _post_json(
                    f"{origin}/api/craft-brief",
                    {
                        "action": "rank",
                        "episode": ep,
                        "use_saved_model": False,
                        "candidates": [
                            "Haley wandered off without saying anything.",
                            'Francine checked the hallway. "Stay sharp." Brass deadbolt slid home cleanly.',
                        ],
                    },
                    origin,
                )
                self.assertEqual(st_rank, 200)
                self.assertEqual(res_rank["status"], "PROPOSED")
                self.assertIn("Brass deadbolt", res_rank["winner"]["text"])
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
