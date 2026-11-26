"""Tests for Mean Girls -> Three Little Bitches Minds, editable Alternate Spring Break Scene 4, and Tapped Out smart graph synthesis."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from prose_engine.mean_girls_minds import (
    attach_mean_girls_minds_to_form_graph,
    build_three_little_bitches_minds,
    parse_srt_cues,
)
from prose_engine.spring_alternate import (
    build_alternate_spring_packet,
    validate_alternate_spring_candidate,
)
from prose_engine.tapped_out_graph import (
    cook_with_character_graph_synthesis,
    synthesize_character_graph_for_script,
)
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore
from story_graph.fx06_scene import PERFUME_LINE

REPO_ROOT = Path(__file__).resolve().parents[1]
MEAN_GIRLS_DIR = REPO_ROOT / "deliverables" / "NOIR_FX06_GAG_COLLECTION_20261116" / "Mean Girls (2004)"
SCENT_PATH = REPO_ROOT / "deliverables" / "NOIR_FX06_GAG_COLLECTION_20261116" / "rainee_split_mind_support.json"

SYNTHETIC_SRT = """1
00:10:03,000 --> 00:10:06,000
REGINA: Stop talking. She is answering my question now.

2
00:10:07,000 --> 00:10:09,500
Okay, who did you want to talk to?

3
00:13:47,000 --> 00:13:51,000
GRETCHEN: Wait! You cannot sit with us unless you follow the group rule on Wednesdays.

4
00:14:58,000 --> 00:15:01,000
KAREN: Wait, why does her shirt have a different collar?

5
00:42:10,000 --> 00:42:14,000
REGINA: Post-Halloween revenge betrayal dialogue that must be excluded!
"""

SYNTHETIC_EVIDENCE = {
    "admitted_ids": ["p04-01-intervene", "p04-05-ordinary-rule", "p04-06-rationale-challenged"],
    "quarantined_ids": ["p04-10-hidden-witness"],
    "moments": [
        {
            "id": "p04-01-intervene",
            "window": "public-intervention",
            "span_ms": [602700, 630900],
            "actors": ["Regina", "Gretchen", "Cady"],
            "pressure": "An outsider takes control while Regina steps in.",
            "performed": "Regina redirects the floor and Cady answers inside Regina's frame.",
            "power_change": "Regina reclaims control.",
            "eligibility": "transfer",
            "frame_evidence": [{"absolute_pts_ms": 603000, "frame": "f0.jpg"}],
        },
        {
            "id": "p04-05-ordinary-rule",
            "window": "rule-teaching",
            "span_ms": [826500, 847900],
            "actors": ["Gretchen", "Cady"],
            "pressure": "Gretchen enforces group rules.",
            "performed": "Gretchen explains rules and watches Cady's face.",
            "power_change": "Norms set.",
            "eligibility": "transfer",
            "frame_evidence": [],
        },
        {
            "id": "p04-06-rationale-challenged",
            "window": "rule-challenge",
            "span_ms": [896100, 918500],
            "actors": ["Gretchen", "Karen", "Cady"],
            "pressure": "Karen interrupts with a literal observation.",
            "performed": "Karen asks why the detail contradicts Gretchen.",
            "power_change": "Gretchen shifts rapidly.",
            "eligibility": "transfer",
            "frame_evidence": [],
        },
        {
            "id": "p04-10-hidden-witness",
            "window": "quarantined",
            "span_ms": [950000, 960000],
            "actors": ["Regina"],
            "pressure": "Quarantined scene.",
            "performed": "Excluded.",
            "power_change": "None.",
            "eligibility": "exclude",
            "frame_evidence": [],
        },
        {
            "id": "p99-post-betrayal",
            "window": "betrayal",
            "span_ms": [2520000, 2550000],
            "actors": ["Regina", "Cady"],
            "pressure": "Post-26:35 betrayal.",
            "performed": "Revenge arc.",
            "power_change": "Revenge.",
            "eligibility": "transfer",
            "frame_evidence": [],
        },
    ],
}

SYNTHETIC_DONOR = {
    "access": {"allow_interval_ms": [0, 1_595_000]},
    "actor_cards": [
        {
            "target": "rainee-split-1",
            "tendencies": [{"when": "an outsider speaks up", "try": "Regina takes control of the floor.", "evidence": ["p04-01-intervene"]}],
            "constraint": "Hold frame without film plot.",
        },
        {
            "target": "rainee-split-2",
            "tendencies": [{"when": "group rules apply", "try": "Gretchen reinforces the shared rule.", "evidence": ["p04-05-ordinary-rule"]}],
            "constraint": "Enforce loyalty.",
        },
        {
            "target": "rainee-split-3",
            "tendencies": [{"when": "an excuse overlooks a fact", "try": "Karen blurs out the literal contradiction.", "evidence": ["p04-06-rationale-challenged"]}],
            "constraint": "Interrupt concretely.",
        },
    ],
    "optional_local_relationship_edges": [
        {"from": "rainee-split-1", "to": "rainee-split-2", "context": "pressure", "effect": "Regina backs Gretchen", "evidence": ["p04-01-intervene"]},
    ],
}


class MeanGirlsSpringTappedOutTests(unittest.TestCase):
    def test_mean_girls_dialogue_hooks_to_three_rainee_minds_in_form_graph(self):
        cues = parse_srt_cues(SYNTHETIC_SRT)
        self.assertEqual(len(cues), 5)
        scents = json.loads(SCENT_PATH.read_text(encoding="utf-8")) if SCENT_PATH.is_file() else {
            "rules": [
                {"form": "rainee-split-1", "scent": "tuberose", "perfume": "Gucci Bloom"},
                {"form": "rainee-split-2", "scent": "orange", "perfume": "Chanel Coco"},
                {"form": "rainee-split-3", "scent": "sandalwood", "perfume": "Le Labo Santal 33"},
            ]
        }
        built = build_three_little_bitches_minds(
            linked_evidence=SYNTHETIC_EVIDENCE,
            donor_override=SYNTHETIC_DONOR,
            srt_cues=cues,
            scent_rules=scents,
            timing_cues=("Wait half a beat before flipping the excuse.",),
            include_movie_dir=False,
        )
        self.assertEqual(built["admitted_window_count"], 3)
        self.assertIn("p04-10-hidden-witness", built["quarantined_or_rejected"])
        self.assertIn("p99-post-betrayal", built["quarantined_or_rejected"])
        self.assertEqual([m["scent"] for m in built["minds"]], ["tuberose", "orange", "sandalwood"])
        for m in built["minds"]:
            for donor_name in ("Regina", "Gretchen", "Karen", "Cady"):
                self.assertNotIn(donor_name, m["behavior"])
            self.assertGreaterEqual(m["dialogue_mechanics"]["cue_count"], 1)

        if (MEAN_GIRLS_DIR / "Transcript" / "Full Film.en.srt").is_file():
            real_built = build_three_little_bitches_minds(mean_girls_dir=MEAN_GIRLS_DIR, scent_rules=scents)
            self.assertGreaterEqual(real_built["admitted_window_count"], 10)
            self.assertGreater(real_built["srt_cue_count"], 500)
            self.assertIn("p04-10-hidden-witness", real_built["quarantined_or_rejected"])

        with tempfile.TemporaryDirectory() as tmp:
            forms = FormGraphStore(Path(tmp) / "forms.sqlite")
            receipt = attach_mean_girls_minds_to_form_graph(forms, built)
            self.assertEqual(len(receipt["attached"]), 3)
            # Upstream graph edit changes Rainee 2 Mind card and supports undo_node_data.
            p2 = receipt["attached"][1]["port_id"]
            rev = receipt["revision"]
            forms.change({
                "action": "save_node_data",
                "revision": rev,
                "character": "rainee",
                "node": "data:" + p2,
                "content": {"text_fields": {"behavior": "Edited on board: break ranks and back Haley."}},
            })
            pkt = build_alternate_spring_packet(
                f"INT. BATHROOM - MORNING\nHaley: {PERFUME_LINE}\n\n",
                "[EDITABLE SCENE 4]",
                "\n\n### SCENE 7: ROGER RUTGERS\nRoger: Rutgers awaits.\n",
                built,
                form_store=forms,
                leaving_mode="clothes",
            )
            self.assertIn("Edited on board: break ranks and back Haley.", pkt["writer_brief"])
            forms.change({"action": "undo_node_data", "revision": forms.read()["revision"], "character": "rainee", "node": "data:" + p2})

    def test_alternate_spring_break_scene4_destabilize_fart_and_leaving_modes(self):
        cues = parse_srt_cues(SYNTHETIC_SRT)
        built = build_three_little_bitches_minds(
            linked_evidence=SYNTHETIC_EVIDENCE,
            donor_override=SYNTHETIC_DONOR,
            srt_cues=cues,
            include_movie_dir=False,
        )
        prefix = f"INT. BATHROOM - MORNING\nHaley: {PERFUME_LINE}\n\n"
        suffix = "\n\n### SCENE 7: ROGER\nRoger: Takeover starts now.\n"

        for mode in ("relapse", "clothes"):
            pkt = build_alternate_spring_packet(
                prefix,
                "[SCENE 4 PLACEHOLDER]",
                suffix,
                built,
                leaving_mode=mode,
                timing_notes=("Hold 0.5 s before the second blast lands.",),
            )
            extra = "Nurse Franny packs the clothes into her red overnight bag with keys and three lasagna trays." if mode == "clothes" else "Haley holds the house keys and three trays of lasagna on the landing."
            good_candidate = (
                "### SCENE 4: THE THREE LITTLE BITCHES\n"
                "Rainee splits into three little bitches behind the door.\n"
                "Rainee 1: Close the door.\n"
                "Rainee 2: Follow the bathroom rule.\n"
                "Rainee 3: The fan switch is off.\n"
                "Francine steps in with her voice alone and brings the three back together.\n"
                "Rainee swells into Rainee Peter Griffen; Francine laughs and asks for Nurse Franny.\n"
                "Rainee Peter Griffen: Stand back, Haley!\n"
                "Nurse Franny steps forward as Rainee Peter Griffen lets loose a massive fart blast that sends Haley halfway down the hall.\n"
                "Rainee Peter Griffen destabilizes right back into the same Three Little Bitches.\n"
                "Together they rip a second fart blast smelling of tuberose, orange, and sandalwood that farts their bitch daughter Haley the rest of the way down the hall.\n"
                "Rainee 1: Verdict: hallway cleared.\n"
                "Rainee 2: And nobody leaves until they admit it.\n"
                "Rainee 3: She slid past two coat hooks.\n"
                f"{extra}\n"
            )
            check = validate_alternate_spring_candidate(good_candidate, pkt)
            self.assertTrue(check["valid"], check["issues"])
            self.assertIn(PERFUME_LINE, check["assembled_text"])
            self.assertTrue(check["assembled_text"].endswith(suffix))

            bad_peter = good_candidate.replace("Rainee Peter Griffen: Stand back, Haley!", "Peter: Stand back!").replace("into Rainee Peter Griffen", "into Peter")
            bad_check = validate_alternate_spring_candidate(bad_peter, pkt)
            self.assertFalse(bad_check["valid"])
            self.assertTrue(any("Rainee Peter Griffen" in msg for msg in bad_check["issues"]))

    def test_tapped_out_rewrite_reuses_existing_adds_holly_and_attaches_big_tiddy_steve(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tl = TimelineStore(root / "timeline.sqlite")
            forms = FormGraphStore(root / "forms.sqlite")
            tl.add_starter_cards()
            script_v1 = (
                "INT. STUDIO LOBBY - NIGHT\n\n"
                "Francine: Keep the hallway clear.\n\n"
                "Stella transforms into Big Tiddy Steve in her yellow polo.\n\n"
                "STELLA (Big Tiddy Steve): The buttons barely held.\n\n"
                "Big Tiddy Nerdy Female Boy Stella: Check the cube reading.\n\n"
                "Big Tiddy Nerdy Female Boy Stell: Truncated legacy cue test.\n\n"
                "Stella shifts into Turbo Dork Mode.\n\n"
                "Holly: Welcome to my studio, girls.\n\n"
                "Holly Graham smiles beside Haleys station.\n"
            )
            tapped_head = tl.get_episode("tapped-out")["head"]
            tl.save("tapped-out", tapped_head, script=script_v1, source_name="tapped-rewrite-1")
            res1 = cook_with_character_graph_synthesis(tl, forms, "tapped-out")
            syn1 = res1["synthesis"]
            self.assertIn("francine", syn1["reused_characters"])
            self.assertIn("stella", syn1["reused_characters"])
            self.assertEqual(syn1["added_characters"], [{"character_id": "holly", "label": "Holly"}])
            # New narrative form attaches cleanly under existing stella junction, while known Big Tiddy Steve is reused on stella!
            self.assertTrue(any(f["character_id"] == "stella" and f["label"] == "Turbo Dork Mode" for f in syn1["added_forms"]))
            self.assertTrue(any(f["character_id"] == "stella" and f["form_id"] == "big_tiddy_steve_stella" for f in syn1["reused_forms"]))
            stella_speakers = [b for b in syn1["speaker_blocks"] if b["speaker"] == "stella"]
            self.assertEqual(len(stella_speakers), 3)
            self.assertTrue(all(b["form"] == "big_tiddy_steve_stella" for b in stella_speakers))
            holly_blocks = [b for b in syn1["speaker_blocks"] if b["speaker"] == "holly"]
            self.assertEqual(len(holly_blocks), 1)
            self.assertEqual(res1["cook"]["stage2"]["unresolved_blocks"], 0)

            # Second rewrite pass must REUSE Holly and Stella's forms cleanly without adding duplicate characters!
            script_v2 = script_v1 + "\nHolly: Roll the next scene.\n\nBig Tiddy Steve: Ready on set.\n"
            syn2 = synthesize_character_graph_for_script(script_v2, form_store=forms)
            self.assertIn("holly", syn2["reused_characters"])
            self.assertIn("stella", syn2["reused_characters"])
            self.assertEqual(syn2["added_characters"], [])
            self.assertEqual(syn2["added_forms"], [])


if __name__ == "__main__":
    unittest.main()
