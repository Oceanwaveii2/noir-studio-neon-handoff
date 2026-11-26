"""Epic 4 verification: occurrence-safe 0/25/50/75/100% slot infill & structural seam validator."""
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
from prose_engine.scoped_pipeline import build_packet, evaluate_infill_proposal, validate_output
from prose_engine.slot_infill import (
    PROTECTION_TIERS,
    apply_slot_fills,
    plan_infill_slots,
    tier_policy,
    validate_infill_seams,
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


class TestEpic4SlotInfill(unittest.TestCase):
    def test_tier_policies_cover_0_25_50_75_100_and_slot_partitioning(self):
        modes = [tier_policy(t).mode for t in PROTECTION_TIERS]
        self.assertEqual(modes, ["open_infill", "loose_infill", "balanced_rewrite", "tight_polish", "verbatim"])
        self.assertTrue(tier_policy(0).editable)
        self.assertFalse(tier_policy(100).editable)

        src = "AAABBBCCCDDDEEE"
        plan = plan_infill_slots(
            src,
            ranges=[(0, 3, 100), (3, 6, 75), (6, 9, 50), (9, 12, 25)],
            default_tier=0,
            base_offset=10,
        )
        self.assertEqual([s.tier for s in plan.slots], [100, 75, 50, 25, 0])
        self.assertEqual([(s.abs_start, s.abs_end) for s in plan.slots], [(10, 13), (13, 16), (16, 19), (19, 22), (22, 25)])
        self.assertEqual("".join(s.source_text for s in plan.slots), src)

    def test_duplicate_occurrence_disambiguation_and_lock_immutability(self):
        src = "Hold. Wait here. Hold. Wait there. Hold."
        # Lock occurrence 0 (0..5) and occurrence 2 (35..40); keep middle Hold. (17..22) discrete at 25% over 0% gaps
        plan = plan_infill_slots(src, ranges=[(0, 5, 100), (17, 22, 25), (35, 40, 100)], default_tier=0)
        locked = plan.locked_slots()
        self.assertEqual([(s.occurrence_index, s.occurrence_total) for s in locked], [(0, 3), (2, 3)])

        # Ambiguous bare string key refuses to guess which duplicate "Hold."
        with self.assertRaisesRegex(ValueError, "Ambiguous duplicate occurrence"):
            apply_slot_fills(plan, {"Hold.": "Stay."})

        # Targeting locked copy by exact occurrence raises ValueError
        with self.assertRaisesRegex(ValueError, "100% locked"):
            apply_slot_fills(plan, {("Hold.", 0): "Stay."})

        # Targeting middle copy (occurrence 1) succeeds and preserves occurrences 0 and 2 cleanly
        applied = apply_slot_fills(plan, {("Hold.", 1): "Stay."}, enforce_tier_fidelity=False)
        self.assertTrue(applied["validation"]["valid"])
        self.assertEqual(applied["text"], "Hold. Wait here. Stay. Wait there. Hold.")
        self.assertEqual(applied["source_edit"], (17, 22))

    def test_seam_validator_catches_collisions_headings_quotes_echoes_and_tier_drift(self):
        # 1. Word collision across 100% <-> 25% seam
        p_word = plan_infill_slots("Haley stepped back.", ranges=[(0, 5, 100)], default_tier=25)
        rep_word = validate_infill_seams(p_word, "Haleystepped back.", enforce_tier_fidelity=False)
        self.assertFalse(rep_word.valid)
        self.assertTrue(any(f.code == "seam_word_collision" for f in rep_word.findings))

        # 2. Scene heading collapse across seam
        p_head = plan_infill_slots(
            "Haley rinsed the cup.\n\n### SCENE 2: GARAGE\nQuiet.",
            ranges=[(23, 51, 100)],
            default_tier=50,
        )
        rep_head = validate_infill_seams(
            p_head,
            "Haley dried the mug.### SCENE 2: GARAGE\nQuiet.",
            enforce_tier_fidelity=False,
        )
        self.assertFalse(rep_head.valid)
        self.assertTrue(any(f.code == "seam_heading_collapse" for f in rep_head.findings))

        # 3. Quote imbalance across seam
        p_quote = plan_infill_slots('FRANCINE: "Leave now."', ranges=[(0, 10, 100)], default_tier=25)
        rep_quote = validate_infill_seams(p_quote, 'FRANCINE: "Leave soon.', enforce_tier_fidelity=False)
        self.assertFalse(rep_quote.valid)
        self.assertTrue(any(f.code == "seam_quote_imbalance" for f in rep_quote.findings))

        # 4. >=5-word verbatim seam echo against 100% neighbor
        prefix = "Morning sunlight slanted across kitchen linoleum tiles "
        src_echo = prefix + "while Haley poured dark roast coffee."
        p_echo = plan_infill_slots(src_echo, ranges=[(0, len(prefix), 100)], default_tier=25)
        cand_echo = prefix + "across kitchen linoleum tiles carefully."
        # Wait: exact trailing 5 words of prefix are "sunlight slanted across kitchen linoleum tiles" -> match last 5:
        trailing5 = " ".join(prefix.split()[-5:])
        rep_echo = validate_infill_seams(p_echo, prefix + trailing5 + " as Haley waited.", enforce_tier_fidelity=False)
        self.assertFalse(rep_echo.valid)
        self.assertTrue(any(f.code == "seam_verbatim_echo" for f in rep_echo.findings))

        # 5. Tier 75% tight_polish vs 50% vs 0%
        line = "Francine Ling rinsed the cracked porcelain mug twice before dawn."
        p75 = plan_infill_slots(line, ranges=[], default_tier=75)
        ok75 = apply_slot_fills(p75, {0: "Francine Ling rinsed the chipped porcelain mug twice before dawn."})
        self.assertTrue(ok75["validation"]["valid"])
        with self.assertRaisesRegex(ValueError, "tier_anchor_loss|below required"):
            apply_slot_fills(p75, {0: "Someone washed a dish later on."})

        p50 = plan_infill_slots(line, ranges=[], default_tier=50)
        ok50 = apply_slot_fills(p50, {0: "Before dawn, Francine Ling washed that cracked mug twice."})
        self.assertTrue(ok50["validation"]["valid"])

        p0 = plan_infill_slots(line, ranges=[], default_tier=0)
        ok0 = apply_slot_fills(p0, {0: "Cold water splashed into the sink."})
        self.assertTrue(ok0["validation"]["valid"])

    def test_scoped_pipeline_and_studio_slot_infill_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "timeline.sqlite"
            store = TimelineStore(db_path)
            ep = "infill-ep"
            script = 'FRANCINE: "No coffee yet."\n\nHaley stepped into the quiet Ling kitchen.'
            store.create_episode(ep, "Infill Episode", "main", 10)
            store.save(ep, 0, script=script, source_name="infill.txt")
            book = NotebookStore(store)
            state = book.open(ep)
            lock = {"id": "lock-line", "start": 0, "end": 26, "value": 100, "sha256": digest(script[:26])}
            book.save(ep, state["revision"], 1, state["blocks"], 50, [lock])
            wls = WorldLawStore(store)
            cur_laws = wls.open()
            wls.save(cur_laws["revision"], [
                *cur_laws["laws"],
                {"id": "no-smith-bleed", "name": "No Smith", "statement": "Francine is Ling, not Smith.", "enabled": True, "matcher": "literal", "phrases": ["Francine Smith"]},
            ])

            packet = build_packet(store, ep, 0, 1, 0, len(script), junctions=AFM_JUNCTIONS)
            ok = evaluate_infill_proposal(
                packet,
                {1: "\n\nHaley walked quickly into the quiet Ling kitchen."},
                default_tier=50,
            )
            self.assertTrue(ok["valid"], ok["issues"])

            bad_canon = evaluate_infill_proposal(
                packet,
                {1: "\n\nHaley met Francine Smith in the quiet Ling kitchen."},
                default_tier=50,
            )
            self.assertFalse(bad_canon["valid"])
            self.assertTrue(any("world-law" in msg.lower() or "conflict" in msg.lower() for msg in bad_canon["issues"]), bad_canon["issues"])

            # validate_output catches unbalanced quotes/seam echo across the 100% seam too
            dangling = validate_output(packet, 'FRANCINE: "No coffee yet."\n\nHaley whispered "hello inside.')
            self.assertTrue(dangling)

            # Studio HTTP endpoint smoke check (/api/slot-infill + 403 foreign origin)
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
                status_bad, _ = _post_json(f"{origin}/api/slot-infill", {"action": "plan", "episode": ep}, "http://evil.example")
                self.assertEqual(status_bad, 403)

                st_plan, res_plan = _post_json(f"{origin}/api/slot-infill", {"action": "plan", "episode": ep}, origin)
                self.assertEqual(st_plan, 200)
                self.assertEqual([s["tier"] for s in res_plan["plan"]["slots"]], [100, 50])

                edit_slot_id = res_plan["plan"]["slots"][1]["slot_id"]
                st_val, res_val = _post_json(
                    f"{origin}/api/slot-infill",
                    {"action": "validate", "episode": ep, "fills": {edit_slot_id: "\n\nHaley paused inside the quiet Ling kitchen."}},
                    origin,
                )
                self.assertEqual(st_val, 200)
                self.assertTrue(res_val["valid"], res_val["issues"])
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
