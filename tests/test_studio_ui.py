"""
Unit tests for tools/studio_ui.py: Interactive Graph & Block Editor.
Includes full regression verification for Milestones M1-M6.
"""

import json
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from tools.studio_ui import StudioRequestHandler, run_server


class TestStudioUI(unittest.TestCase):
    PORT = 8795

    @classmethod
    def setUpClass(cls):
        cls.fixture_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixture_dir.cleanup)
        fixture = Path(cls.fixture_dir.name)
        cls.server_thread = threading.Thread(
            target=run_server,
            kwargs={"port": cls.PORT, "timeline_path": fixture / 'timeline.sqlite',
                    "form_store": fixture / 'forms.sqlite'},
            daemon=True
        )
        cls.server_thread.start()
        time.sleep(1)

    def test_get_index_html(self):
        url = f"http://127.0.0.1:{self.PORT}/"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode("utf-8")
            self.assertIn("Noir Fiction Studio", html)
            self.assertIn("nodeContainer", html)
            self.assertIn("blocksContainer", html)
            self.assertIn("leftSidebar", html)
            self.assertIn("rightInspector", html)
            self.assertIn("splitResizer", html)
            self.assertIn("btnRecompute", html)
            self.assertIn("rangeVoiceArch", html)
            self.assertIn("American Foxy Mom", html)
            self.assertIn("Chapter 16: The Spring Break Protocol", html)
            self.assertIn("Scene 1 · Kitchen Briefing", html)
            # Verify purge of foreign mockup story data
            self.assertNotIn("Jade City", html)
            self.assertNotIn("Rangiku", html)
            self.assertNotIn("BBL Episodes", html)
            self.assertNotIn("Merchant Identity", html)
            self.assertNotIn("MERCHANT COGNITION", html)
            self.assertNotIn("Rainee Transformation", html)
            # Verify Milestone U2: zero inline composer notes in prose and continuous parchment
            self.assertNotIn("Composer note:", html)
            self.assertNotIn("composerNoteHtml", html)
            self.assertIn("Baba Ling Invariant (Protected)", html)
            self.assertIn("Zero-Smith Matrilineal Guard", html)
            self.assertIn("Physical Affordance Rule", html)
            self.assertIn("display: block;", html)
            self.assertIn("height: auto;", html)
            self.assertIn("tabReader", html)
            self.assertIn("setAppView", html)
            self.assertIn("screenplay-jump-bar", html)
            # Verify Milestone U4: single clean slider track and functional toolbar controls
            self.assertNotIn("slider-bar-track", html)
            self.assertIn("flex-wrap: wrap;", html)
            self.assertIn("triggerUndo", html)
            self.assertIn("toggleTraceBadges", html)
            self.assertIn("showEvidenceMatrix", html)
            self.assertIn("initKeyboardShortcuts", html)

    def test_get_reader_html(self):
        url = f"http://127.0.0.1:{self.PORT}/reader"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode("utf-8")
            self.assertIn("American Foxy Mom", html)
            # Verify unified Eclipse Parchment styling on /reader
            self.assertIn("parchment-card", html)
            self.assertIn("#101113", html)
            self.assertIn("#f4f1ea", html)
            self.assertIn("#c49a67", html)

    def test_forensic_u1_to_u5_unification_invariants(self):
        """Comprehensive verification of Milestones U1-U5 forensic unification."""
        url = f"http://127.0.0.1:{self.PORT}/"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode("utf-8")

            # U1 Invariants: 100% purge of dummy mockup data
            for banned in ["Jade City", "Rangiku", "BBL Episodes", "Merchant Identity", "MERCHANT COGNITION", "Rainee Transformation"]:
                self.assertNotIn(banned, html, f"Banned foreign mockup string '{banned}' found in HTML")

            # U1 Invariants: American Foxy Mom Chapter 16 scenes and sources
            for scene in ["Scene 1 · Kitchen Briefing", "Scene 2 · Master Suite", "Scene 3 · Porcelain Crucible", "Scene 4 · Peter Griffin Morph", "Scene 5 · Nurse Franny Morph", "Scene 6 · Departure"]:
                self.assertIn(scene, html, f"Missing real scene item: '{scene}'")

            for src in ["American Dad Corpus", "Quahog / Stewie Farce", "Húxiān Fox Clan Lore", "1990s Glamour / Cinemax"]:
                self.assertIn(src, html, f"Missing real evidence source: '{src}'")

            # U2 Invariants: continuous parchment CSS and zero inline composer notes
            self.assertIn("display: block;", html)
            self.assertIn("height: auto;", html)
            self.assertNotIn("Composer note:", html)
            self.assertNotIn("composerNoteHtml", html)
            self.assertIn("Baba Ling Invariant (Protected)", html)
            self.assertIn("Zero-Smith Matrilineal Guard", html)
            self.assertIn("Physical Affordance Rule", html)

            # U3 Invariants: In-app screenplay reader mode & jump bar
            self.assertIn("tabReader", html)
            self.assertIn("setAppView", html)
            self.assertIn("screenplay-jump-bar", html)

            # U4 Invariants: single slider track per row & responsive toolbar
            self.assertNotIn("slider-bar-track", html)
            self.assertIn("flex-wrap: wrap;", html)
            self.assertIn("triggerUndo", html)
            self.assertIn("triggerRedo", html)
            self.assertIn("toggleTraceBadges", html)
            self.assertIn("toggleAttachMode", html)
            self.assertIn("showEvidenceMatrix", html)

            # G1 Invariants: Real Graphing Software (Cytoscape.js + LiteGraph.js) & no inline flex override on #textPane
            self.assertIn("/vendor/cytoscape.min.js", html)
            self.assertIn("/vendor/litegraph.min.js", html)
            self.assertIn("initCytoscapeEngine", html)
            self.assertIn("initLiteGraphEngine", html)
            self.assertIn("setGraphEngine", html)
            self.assertIn("litegraphCanvas", html)
            self.assertNotIn("tp.style.display = 'flex'", html)

            # G2, C1, C2 Invariants: Authoring HUD, Scene Banners, Zen Mode, Single Filled Slider Gradient, Cache-Control, Bidirectional Wire Sync, Gutter Strip, ScrollSpy
            self.assertIn("authoringHud", html)
            self.assertIn("toggleZenMode", html)
            self.assertIn("SCENE_BANNERS", html)
            self.assertIn("setSliderGradient", html)
            self.assertIn("graphLegendPill", html)
            self.assertIn("syncLiteGraphToModel", html)
            self.assertIn("cycleCharacterBeats", html)
            self.assertIn("beat-gutter", html)
            self.assertIn("toggleBeatFreeze", html)
            self.assertIn("enableInlineEdit", html)
            self.assertIn("hudProgressFill", html)
            self.assertIn("filterBeatsBySpeaker", html)
            self.assertIn("initScrollSpy", html)
            self.assertIn("runPlotGapScan", html)
            self.assertNotIn("alert(", html)
            self.assertIn("no-store", resp.headers.get("Cache-Control", ""))

        # Verify local vendor static serving
        for asset in ["/vendor/cytoscape.min.js", "/vendor/litegraph.min.js", "/vendor/litegraph.css"]:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.PORT}{asset}") as vresp:
                self.assertEqual(vresp.status, 200)
                self.assertGreater(len(vresp.read()), 5000)

    def test_milestone_g1_g2_real_graph_engines(self):
        """Milestone V1 verification of G1 & G2 real graphing engines (Cytoscape.js DAG + LiteGraph.js Wires)."""
        url = f"http://127.0.0.1:{self.PORT}/"
        with urllib.request.urlopen(url) as resp:
            html = resp.read().decode("utf-8")
            self.assertIn("◈ Cytoscape DAG", html)
            self.assertIn("⚡ LiteGraph Wires", html)
            self.assertIn("runAutoLayout", html)
            self.assertIn("syncLiteGraphToModel", html)
            self.assertIn("cycleCharacterBeats", html)
            self.assertIn("graphLegendPill", html)
            self.assertNotIn("<svg id=\"cableSvg\"", html)

    def test_milestone_c1_c2_compose_overhaul(self):
        """Milestone V1 verification of C1 & C2 Compose View typography, gutter trace, HUD & Zen Mode."""
        url = f"http://127.0.0.1:{self.PORT}/"
        with urllib.request.urlopen(url) as resp:
            html = resp.read().decode("utf-8")
            self.assertIn("BUILD v2.6-LIVE", html)
            self.assertIn("beat-gutter", html)
            self.assertIn("toggleBeatFreeze", html)
            self.assertIn("enableInlineEdit", html)
            self.assertIn("hudProgressFill", html)
            self.assertIn("filterBeatsBySpeaker", html)
            self.assertIn("toggleZenMode", html)
            self.assertIn("initScrollSpy", html)
            self.assertNotIn("alert(", html)

    def test_get_api_state_17_nodes(self):
        url = f"http://127.0.0.1:{self.PORT}/api/state"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("nodes", data)
            groups = data["character_junctions"]
            self.assertEqual(len(groups), 5)
            ports = [form["port_id"] for group in groups for form in group["forms"]]
            self.assertEqual(len(ports), len(set(ports)))
            stella = next(group for group in groups if group["character_id"] == "stella")
            self.assertEqual(stella["forms"][-1]["status"], "planning_only")
            self.assertIn("connections", data)
            self.assertIn("blocks", data)

            self.assertEqual(len(data["nodes"]), 17, "Expected exactly 17 nodes on canvas")
            self.assertEqual(len(data["connections"]), 16, "Expected exactly 16 connections")

            node_types = [n["type"] for n in data["nodes"]]
            self.assertIn("personality_data", node_types)
            self.assertIn("appearance", node_types)
            self.assertIn("transformation", node_types)
            self.assertIn("dialogue_dial", node_types)
            self.assertIn("prose_conditioner", node_types)
            self.assertIn("output", node_types)

            node_ids = {n["id"]: n for n in data["nodes"]}
            # Verify Transformation Nodes
            self.assertIn("node_trans_rainee_peter", node_ids)
            self.assertIn("node_trans_franny_anderson", node_ids)
            self.assertIn("node_personality_rainee_peter", node_ids)
            self.assertIn("node_personality_franny_anderson", node_ids)

            # Peter Variant Invariants
            peter_morph = node_ids["node_trans_rainee_peter"]["data"]
            self.assertIn("butt-chin", peter_morph["facial_features"])
            self.assertIn("2 chairs enforced", peter_morph["affordance"])

            # Franny Variant Invariants
            franny_morph = node_ids["node_trans_franny_anderson"]["data"]
            self.assertIn("bouffant", franny_morph["hair_and_head"])
            self.assertIn("halter", franny_morph["wardrobe"])

    def test_speaker_attributions_and_zero_smith(self):
        url = f"http://127.0.0.1:{self.PORT}/api/state"
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            blocks = data["blocks"]

            speakers = {b["speaker"] for b in blocks if b["speaker"]}
            self.assertIn("RAINEE", speakers)
            self.assertIn("FRANCINE", speakers)
            self.assertIn("HALEY", speakers)
            self.assertIn("STELLA", speakers)
            self.assertIn("ROGER", speakers)
            self.assertIn("RAINEE (PETER)", speakers)
            self.assertIn("NURSE FRANNY ANDERSON", speakers)

            # Verify Zero Smith invariant
            for b in blocks:
                text = b["text"]
                self.assertNotIn("Francine Smith", text)
                self.assertNotIn("Haley Smith", text)
                self.assertNotIn("Stan Smith", text)
                self.assertNotIn("the Smiths", text)

            # Verify Baba Ling inguinal hernia surgery invariant
            baba_blocks = [b for b in blocks if "ancestral farting" in b["text"] or "inguinal hernia" in b["text"]]
            self.assertTrue(len(baba_blocks) > 0, "Baba Ling surgical recovery must be present")

    def test_post_api_compute(self):
        state_url = f"http://127.0.0.1:{self.PORT}/api/state"
        with urllib.request.urlopen(state_url) as resp:
            state = json.loads(resp.read().decode("utf-8"))

        compute_url = f"http://127.0.0.1:{self.PORT}/api/compute"
        payload = json.dumps({
            "nodes": state["nodes"],
            "blocks": state["blocks"][:5]
        }).encode("utf-8")

        req = urllib.request.Request(
            compute_url,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            result = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(result["success"])
            self.assertEqual(len(result["blocks"]), 5)
            self.assertGreater(result["burstiness"], 4.5, "Cadence burstiness must meet quality gate sigma >= 4.5")

    def test_tier1_tier2_tier3_anti_slop_defense(self):
        """Verify the 3-Tier Anti-AI-ism defense system."""
        # Tier 1 & 2: Verify tics blacklist catches rule lecturing, punchline echoes, subtext spoilers
        from prose_engine.voice.tics import blacklisted_cliches
        from prose_engine.voice.slop import surgical_scrub

        sample_slop = (
            "Rainee hesitated, because in this world the celestial fox laws dictated that her power was limited. "
            "She turned the brass latch, signaling her readiness to leave. 'I am ready,' Francine purred."
        )
        cliches = blacklisted_cliches(sample_slop)
        self.assertTrue(any("because in this world" in c for c in cliches), f"Expected rule lecturing hit in {cliches}")
        self.assertTrue(any("signaling her readiness" in c for c in cliches), f"Expected subtext spoiler hit in {cliches}")

        # Tier 3: Verify surgical_scrub cleans subtext tails and normalizes said-bookisms
        cleaned, actions = surgical_scrub(sample_slop)
        self.assertNotIn("purred", cleaned)
        self.assertIn("said", cleaned)
        self.assertNotIn("signaling her readiness", cleaned)

        # Tier 3: Verify live /api/scrub endpoint
        scrub_url = f"http://127.0.0.1:{self.PORT}/api/scrub"
        payload = json.dumps({
            "blocks": [{"id": "b1", "index": 0, "text": "She clicked the latch, signaling her departure."}]
        }).encode("utf-8")
        req = urllib.request.Request(scrub_url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["success"])
            self.assertNotIn("signaling her departure", data["blocks"][0]["text"])

        # Verify studio UI buttons and functions
        with urllib.request.urlopen(f"http://127.0.0.1:{self.PORT}/") as r:
            html = r.read().decode("utf-8")
            self.assertIn("btnHudClean", html)
            self.assertIn("cleanAiTells", html)
            self.assertIn("runAiIsmAudit", html)
            self.assertIn("drawerRefImage", html)
            self.assertIn("CANON VISUAL REFERENCE", html)

    def test_image_serving(self):
        url = f"http://127.0.0.1:{self.PORT}/images/image9.png"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Content-Type"), "image/png")
            data = resp.read()
            self.assertGreater(len(data), 1000)

    def test_step5_undo_redo_controls_present(self):
        import subprocess
        import sys

        with urllib.request.urlopen(f"http://127.0.0.1:{self.PORT}/") as r:
            html = r.read().decode("utf-8")
        for control_id in ("draftFavoriteUndo", "draftFavoriteRedo", "notebookRedo", "lawsRedo", "anchorRedo", "review-redo"):
            self.assertIn(control_id, html)
        with urllib.request.urlopen(f"http://127.0.0.1:{self.PORT}/assets/studio_client.js") as r:
            client_js = r.read().decode("utf-8")
        self.assertIn("Standalone mode has local slider history only", client_js)
        self.assertIn("return changeWorkspaceHistory('undo');", client_js)
        self.assertIn("return changeWorkspaceHistory('redo');", client_js)
        cli_help = subprocess.run(
            [sys.executable, "-m", "prose_engine.cli", "editorial", "--help"],
            capture_output=True, text=True, check=True, cwd=str(Path(__file__).resolve().parents[1]),
        )
        self.assertIn("redo", cli_help.stdout)


if __name__ == "__main__":
    unittest.main()
