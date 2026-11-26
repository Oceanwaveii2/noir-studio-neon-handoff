"""Regression and parity audit tests for Noir Fiction Studio v2 (/v2, M0-M7)."""

import json
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from tools.studio_ui import run_server

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_ASSETS_DIR = REPO_ROOT / "tools" / "assets" / "v2"

V2_CSS_ASSETS = (
    "/assets/v2/tokens.css",
    "/assets/v2/shell.css",
    "/assets/v2/compose.css",
    "/assets/v2/timeline.css",
    "/assets/v2/graph.css",
    "/assets/v2/beat.css",
    "/assets/v2/prose.css",
    "/assets/v2/shelf.css",
    "/assets/v2/analysis_lab.css",
)

V2_JS_ASSETS = (
    "/assets/v2/api.js",
    "/assets/v2/store.js",
    "/assets/v2/splitter.js",
    "/assets/v2/compose.js",
    "/assets/v2/timeline.js",
    "/assets/v2/graph_state.js",
    "/assets/v2/graph_engine.js",
    "/assets/v2/graph_controller.js",
    "/assets/v2/graph_canvas_view.js",
    "/assets/v2/graph.js",
    "/assets/v2/beat.js",
    "/assets/v2/prose.js",
    "/assets/v2/shelf.js",
    "/assets/v2/analysis_lab.js",
    "/assets/v2/sound.js",
    "/assets/v2/app.js",
)


class TestStudioV2UI(unittest.TestCase):
    PORT = 8796

    @classmethod
    def setUpClass(cls):
        cls.fixture_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixture_dir.cleanup)
        fixture = Path(cls.fixture_dir.name)
        cls.server_thread = threading.Thread(
            target=run_server,
            kwargs={
                "port": cls.PORT,
                "timeline_path": fixture / "timeline.sqlite",
                "form_store": fixture / "forms.sqlite",
            },
            daemon=True,
        )
        cls.server_thread.start()
        time.sleep(1)

    def _get(self, path: str) -> tuple[int, str]:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.PORT}{path}") as resp:
            return resp.status, resp.read().decode("utf-8")

    def _get_json(self, path: str) -> tuple[int, dict]:
        code, body = self._get(path)
        return code, json.loads(body)

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.PORT}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{self.PORT}",
            },
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_v2_shell_and_assets_decoupled(self):
        status, html = self._get("/v2")
        self.assertEqual(status, 200)
        self.assertIn('id="v2App"', html)
        self.assertIn("/assets/v2/app.js", html)
        self.assertIn("/vendor/cytoscape.min.js", html)
        # Guardrail: zero legacy stylesheet or script coupling
        self.assertNotIn("/assets/studio_styles.css", html)
        self.assertNotIn("/assets/studio_client.js", html)

        for asset_path in (*V2_CSS_ASSETS, *V2_JS_ASSETS):
            code, body = self._get(asset_path)
            self.assertEqual(code, 200, asset_path)
            self.assertTrue(len(body) > 50, asset_path)

    def test_v2_css_zero_important_and_paired_tokens(self):
        for css_file in sorted(V2_ASSETS_DIR.glob("*.css")):
            content = css_file.read_text(encoding="utf-8")
            self.assertNotIn("!important", content, f"{css_file.name} must not use !important")

        tokens = (V2_ASSETS_DIR / "tokens.css").read_text(encoding="utf-8")
        self.assertIn('body[data-theme="racing"]', tokens)
        self.assertIn('body[data-theme="classic"]', tokens)
        for token in (
            "--surface-chrome:",
            "--ink-on-chrome:",
            "--surface-paper:",
            "--ink-on-paper:",
            "--accent-primary:",
            "--ink-on-accent:",
            "--status-ok-bg:",
            "--status-ok-ink:",
            "--status-err-bg:",
            "--status-err-ink:",
        ):
            self.assertEqual(tokens.count(token), 2, f"{token} must be defined in both themes")

    def test_v2_backend_api_parity(self):
        code, tl = self._get_json("/api/timeline")
        self.assertEqual(code, 200)
        self.assertIn("cards", tl)
        self.assertIn("branches", tl)

        if not tl["cards"]:
            _, seeded = self._post_json("/api/timeline", {"action": "starters"})
            tl["cards"] = seeded.get("cards", [])

        ep_id = tl["cards"][0]["id"]
        ep_head = tl["cards"][0]["head"]

        _, ep_state = self._get_json(f"/api/state?episode={ep_id}")
        self.assertIn("episode", ep_state)
        self.assertIn("nodes", ep_state)

        _, nb = self._post_json("/api/notebook", {"action": "open", "episode": ep_id})
        self.assertIn("blocks", nb)
        self.assertIn("default_protection", nb)

        _, fg = self._get_json(f"/api/form-graph?episode={ep_id}")
        self.assertIn("junctions", fg)

        _, bm = self._get_json(f"/api/beat-map?episode={ep_id}&revision={ep_head}")
        self.assertIn("scenes", bm)
        self.assertIn("beats", bm)

        _, br = self._post_json("/api/beat-rhythm", {"action": "open", "episode": ep_id, "beat": 0})
        self.assertIn("profile", br)

        _, bp = self._get_json("/api/book-policy")
        self.assertIn("sources", bp)

        _, bs = self._get_json("/api/book-status?backend=none&provider=codex-session")
        self.assertEqual(bs["state"], "disabled")

        _, wl = self._post_json("/api/world-laws", {"action": "open"})
        self.assertIn("laws", wl)

    def test_v2_cook_pipeline_endpoints(self):
        _, tl = self._get_json("/api/timeline")
        if not tl["cards"]:
            _, seeded = self._post_json("/api/timeline", {"action": "starters"})
            tl["cards"] = seeded.get("cards", [])
        ep_id = tl["cards"][0]["id"]

        code, cook_job = self._post_json("/api/cook", {"episode": ep_id, "sync": True})
        self.assertEqual(code, 200)
        self.assertEqual(cook_job["status"], "completed")
        self.assertEqual(cook_job["progress"], 100)
        self.assertEqual(len(cook_job["stages"]), 3)
        self.assertIn("stage1", cook_job["result"])
        self.assertIn("stage2", cook_job["result"])
        self.assertIn("stage3", cook_job["result"])

        st_code, status_job = self._get_json(f"/api/cook/status?job_id={cook_job['job_id']}")
        self.assertEqual(st_code, 200)
        self.assertEqual(status_job["status"], "completed")
        self.assertEqual(status_job["job_id"], cook_job["job_id"])

    def test_unified_root_serves_v2_and_legacy_fallback(self):
        from http.server import ThreadingHTTPServer
        from tools.studio_ui import StudioRequestHandler, FormGraphStore, form_targets
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), StudioRequestHandler)
            server.timeline_path = tmp_path / "timeline.sqlite"
            server.form_graph = FormGraphStore(tmp_path / "forms.sqlite", form_targets())
            server.books_dir = REPO_ROOT / "books"
            server.timeline_only = True
            server.initial_episode = "spring-break"
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urllib.request.urlopen(f"{base}/") as resp:
                    self.assertEqual(resp.status, 200)
                    html = resp.read().decode("utf-8")
                    self.assertIn('id="v2App"', html)
                with urllib.request.urlopen(f"{base}/legacy?episode=spring-break") as resp:
                    self.assertEqual(resp.status, 200)
                    legacy_html = resp.read().decode("utf-8")
                    self.assertIn("blocksContainer", legacy_html)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_phase1_obsidian_tokens_sound_graph_and_canon_panel(self):
        _, tokens = self._get("/assets/v2/tokens.css")
        self.assertIn("--surface-canvas: #0b0d12;", tokens)
        self.assertIn("--accent-primary: #ffb07d;", tokens)
        self.assertIn("--accent-secondary: #90e9cd;", tokens)
        self.assertNotIn("#ead6bd", tokens)

        for css_file in sorted(V2_ASSETS_DIR.glob("*.css")):
            css = css_file.read_text(encoding="utf-8")
            self.assertNotIn("--surface-card", css, css_file.name)
            self.assertNotIn("--accent-racing", css, css_file.name)
            self.assertNotIn("v2CookStripeMove", css, css_file.name)

        _, sound_js = self._get("/assets/v2/sound.js")
        self.assertIn("const SOUND_KEY = 'noir_v2_sound_enabled';", sound_js)
        self.assertIn("export function isSoundEnabled()", sound_js)
        self.assertNotIn("prefers-reduced-motion", sound_js)

        _, canvas_js = self._get("/assets/v2/graph_canvas_view.js")
        self.assertIn("fallbackColor", canvas_js)
        self.assertNotIn("PORT_TYPES[pointerState.port?.dataType]?.color", canvas_js)

        _, api_js = self._get("/assets/v2/api.js")
        self.assertIn("/api/canon-diff", api_js)
        self.assertIn("/api/canon-proposals", api_js)
        self.assertIn("/api/slot-infill", api_js)
        self.assertIn("/api/craft-brief", api_js)

        _, prose_js = self._get("/assets/v2/prose.js")
        self.assertIn("v2CanonAuditBtn", prose_js)
        self.assertIn("data-canon-resolve", prose_js)
        self.assertIn("v2SlotPlanBtn", prose_js)
        self.assertIn("v2SlotValidateBtn", prose_js)
        self.assertIn("v2CraftCompileBtn", prose_js)
        self.assertIn("v2SlopCritiqueBtn", prose_js)
        self.assertIn("v2RankDraftsBtn", prose_js)

        for name in (
            "game-finish-plinth.webp",
            "game-form-lab.webp",
            "game-garage-entry.webp",
            "game-rule-marshal.webp",
            "game-season-track.webp",
            "game-standby-pattern.webp",
        ):
            with urllib.request.urlopen(f"http://127.0.0.1:{self.PORT}/assets/v2/{name}") as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers.get("Content-Type"), "image/webp")
                self.assertGreater(len(resp.read()), 1000)

        _, ge_js = self._get("/assets/v2/graph_engine.js")
        for node_type in ("character_switchyard", "mind_state", "media_clip", "world_law_gate"):
            self.assertIn(node_type, ge_js)

        _, compose_js = self._get("/assets/v2/compose.js")
        self.assertIn("buildCodePointMap", compose_js)

        _, app_js = self._get("/assets/v2/app.js")
        self.assertIn("graphSubtab: 'story'", app_js)

        _, tl = self._get_json("/api/timeline")
        if not tl["cards"]:
            _, seeded = self._post_json("/api/timeline", {"action": "starters"})
            tl["cards"] = seeded.get("cards", [])
        ep_id = tl["cards"][0]["id"]
        c_slot, r_slot = self._post_json("/api/slot-infill", {"action": "plan", "episode": ep_id, "beat": 0, "start": 0, "end": 40})
        self.assertEqual(c_slot, 200)
        self.assertGreaterEqual(r_slot["plan"]["slot_count"], 1)

        c_brief, r_brief = self._post_json("/api/craft-brief", {"action": "compile", "episode": ep_id, "beat": 0, "start": 0, "end": 40, "lens_id": "irby"})
        self.assertEqual(c_brief, 200)
        self.assertLessEqual(r_brief["brief"]["byte_size"], 6144)

    def test_track5_canon_auto_correct_and_semantic_review_roundtrip(self):
        _, prose_js = self._get("/assets/v2/prose.js")
        for sym in (
            "v2CanonApplyCorrectionsBtn",
            "v2ScopedApplyFixesBtn",
            "v2ScopedValidationPanel",
            "semantic_review",
            "suggested_corrections",
            "auto_corrected_text",
            "issueLabel",
        ):
            self.assertIn(sym, prose_js)

        _, prose_css = self._get("/assets/v2/prose.css")
        self.assertIn(".v2-correction-diff", prose_css)
        self.assertNotIn("!important", prose_css)

        _, tl = self._get_json("/api/timeline")
        if not tl["cards"]:
            _, seeded = self._post_json("/api/timeline", {"action": "starters"})
            tl["cards"] = seeded.get("cards", [])
        ep = tl["cards"][0]
        ep_id = ep["id"]
        _, nb = self._post_json("/api/notebook", {"action": "open", "episode": ep_id})
        original_blocks = nb["blocks"]
        orig_protection = nb["default_protection"]
        orig_masks = nb["masks"]
        original_text = "".join(b.get("text", "") for b in original_blocks)
        broken_text = original_text + "\n\nStan: Wait until your husband Jeff gets back.\n"
        try:
            _, unlocked_nb = self._post_json(
                "/api/notebook",
                {
                    "action": "save",
                    "episode": ep_id,
                    "revision": nb["revision"],
                    "timeline_revision": nb["timeline_revision"],
                    "blocks": original_blocks,
                    "default_protection": 50,
                    "masks": [],
                },
            )
            _, saved_nb = self._post_json(
                "/api/notebook",
                {
                    "action": "save-document",
                    "episode": ep_id,
                    "revision": unlocked_nb["revision"],
                    "timeline_revision": unlocked_nb["timeline_revision"],
                    "text": broken_text,
                    "graph": None,
                },
            )
            diff_code, diff = self._post_json("/api/canon-diff", {"episode": ep_id, "beat": 0, "queue_proposals": False})
            self.assertEqual(diff_code, 200)
            self.assertTrue(diff.get("corrections"), f"Expected auto-corrections: {diff}")
            self.assertIn("boyfriend Jeff", diff["auto_corrected_text"])

            val_code, val = self._post_json(
                "/api/scoped",
                {
                    "action": "validate",
                    "episode": ep_id,
                    "revision": saved_nb["timeline_revision"],
                    "beat": 0,
                    "start": 0,
                    "end": len(broken_text),
                },
            )
            self.assertEqual(val_code, 200)
            self.assertIn("semantic_review", val)
            self.assertTrue(val.get("suggested_corrections"))
            self.assertIn("boyfriend Jeff", val["auto_corrected_text"])

            _, fixed_nb = self._post_json(
                "/api/notebook",
                {
                    "action": "save-document",
                    "episode": ep_id,
                    "revision": saved_nb["revision"],
                    "timeline_revision": saved_nb["timeline_revision"],
                    "text": diff["auto_corrected_text"],
                    "graph": None,
                },
            )
            re_code, re_diff = self._post_json("/api/canon-diff", {"episode": ep_id, "beat": 0, "queue_proposals": False})
            self.assertEqual(re_code, 200)
            self.assertEqual(re_diff.get("corrections"), [])
            # Restore original blocks & protection cleanly.
            self._post_json(
                "/api/notebook",
                {
                    "action": "save",
                    "episode": ep_id,
                    "revision": fixed_nb["revision"],
                    "timeline_revision": fixed_nb["timeline_revision"],
                    "blocks": original_blocks,
                    "default_protection": orig_protection,
                    "masks": orig_masks,
                },
            )
        finally:
            _, cur_nb = self._post_json("/api/notebook", {"action": "open", "episode": ep_id})
            cur_text = "".join(b.get("text", "") for b in cur_nb["blocks"])
            if cur_text != original_text or cur_nb["default_protection"] != orig_protection:
                self._post_json(
                    "/api/notebook",
                    {
                        "action": "save",
                        "episode": ep_id,
                        "revision": cur_nb["revision"],
                        "timeline_revision": cur_nb["timeline_revision"],
                        "blocks": original_blocks,
                        "default_protection": orig_protection,
                        "masks": orig_masks,
                    },
                )
