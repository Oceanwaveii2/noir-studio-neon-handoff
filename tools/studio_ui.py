"""
Noir Fiction Engine — Multi-Character Studio Workbench & Eclipse Narrative Composer UI
Unified Eclipse Dark Aesthetic (#101113 / #15171a / #c49a67) with side-by-side SPLIT SCREEN default:
- Left Pane (50%): Warm Cream Parchment Manuscript (#f0ede6) with Georgia typography, beat tags, and attach hooks
- Right Pane (50%): Interactive Visual Cognition Graph with dark grid, all 7 character/transformation nodes, and inspector
- Segmented mode toggles [TEXT] [SPLIT] [GRAPH] to switch view instantly
- Dedicated nodes and text mapping for Rainee Peter (Griffin Variant) and Nurse Pamela Franny Anderson
"""

import argparse
import json
import re
import sqlite3
import sys
import threading
import time
import uuid
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, parse_qs, urlparse, quote

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from prose_engine.conditioner import plan_conditioning, apply_proposals
from prose_engine.diagnostics import ProseDiagnosticsAnalyzer
from prose_engine.voice.world_state import WorldState
from prose_engine.style_engine import StyleProfile
from prose_engine.providers.deepseek import BudgetExceeded
from prose_engine.providers.session_attempts import SessionAttemptError
from prose_engine.providers.mock_provider import MockProseProvider
from prose_engine.scoped_references import ReferenceUnavailable
from telemetry.engine_run_logger import EngineRunLogger
from story_graph.scenarios.foxy_mo2 import run_foxy_mo2
from tools.studio_media_http import MediaHTTPMixin
from tools.studio_form_store import FormGraphStore, StaleFormGraph
from story_graph.form_graph_store import attachment_image_type
from story_graph.episode_timeline import TimelineStore

DEFAULT_NOVEL = REPO_ROOT / "work/americandad/foxy_mo2_hybrid_novel.md"
DEFAULT_FORM_STORE = REPO_ROOT / ".app-steward/local/studio/character-forms.sqlite"
STUDIO_ASSETS_DIR = REPO_ROOT / "tools" / "assets"

_COOK_JOBS_LOCK = threading.Lock()
_COOK_JOBS: dict[str, dict] = {}
_COOK_LATEST_BY_EPISODE: dict[str, str] = {}


def _load_studio_asset(name: str) -> str:
    return (STUDIO_ASSETS_DIR / name).read_text(encoding="utf-8").replace("\r\n", "\n")


_DEFAULT_GRAPH = json.loads(_load_studio_asset("studio_default_graph.json"))
DEFAULT_NODES = _DEFAULT_GRAPH["nodes"]
DEFAULT_CONNECTIONS = _DEFAULT_GRAPH["connections"]


def form_targets() -> list[dict]:
    return [{"id": node["id"], "kind": "digital_mind",
             "label": node["title"].removeprefix("Personality: ")}
            for node in DEFAULT_NODES if node["type"] == "personality_data"]


@lru_cache(maxsize=1)
def spring_break_form_status() -> list[dict]:
    return [{"id": packet.beat_id, "label": f"{i}. {packet.name}", "forms": {
                form["port_id"]: form["status"]
                for group in packet.form_context.values() for form in group["forms"]
            }} for i, packet in enumerate(run_foxy_mo2(), 1)]


def build_studio_html() -> str:
    styles = _load_studio_asset("studio_styles.css").rstrip("\n")
    body = _load_studio_asset("studio_body.html").rstrip("\n")
    script = _load_studio_asset("studio_client.js").rstrip("\n")
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        "<title>Noir Fiction Studio</title>\n"
        '<link rel="stylesheet" href="/vendor/litegraph.css">\n'
        '<script src="/vendor/cytoscape.min.js"></script>\n'
        '<script src="/vendor/litegraph.min.js"></script>\n'
        "<style>\n"
        f"{styles}\n"
        "</style>\n"
        '<script src="/assets/compose_blocks.js"></script>\n'
        "</head>\n"
        f"{body}\n\n"
        "<script>\n"
        f"{script}\n\n"
        "</script>\n"
        "</body>\n"
        "</html>\n"
    )


HTML_TEMPLATE = build_studio_html()
class StudioRequestHandler(MediaHTTPMixin, BaseHTTPRequestHandler):
    review_store_path: Optional[Path] = None
    novel_path: Path = DEFAULT_NOVEL

    def _form_store(self, episode=None, *, timeline=None) -> FormGraphStore:
        graph=getattr(self.server, "form_graph", None) or FormGraphStore(None, form_targets())
        path=getattr(self.server,'timeline_path',None)
        if path is not None and Path(path).is_file():
            from story_graph.source_imports import junctions
            with (timeline if timeline is not None else self._timeline_store())._connect() as c:
                if episode:
                    from prose_engine.scene_bridges import scoped_form_store
                    return scoped_form_store(c, graph, episode)
                imported=junctions(c,{})
            return FormGraphStore(graph.path,list(graph.builtins.values()),imported=imported)
        return graph

    def _form_json(self, status: int, payload: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _form_view(self, graph: dict, episode=None) -> dict:
        if episode and getattr(self.server, 'timeline_path', None):
            from prose_engine.scene_bridges import form_graph_view, stage_form_view

            timeline = self._timeline_store()
            graph = stage_form_view(timeline, episode, graph)
            if view := form_graph_view(timeline, episode, graph):
                return view
        return {**graph, "beats": spring_break_form_status() if self.novel_path == DEFAULT_NOVEL else []}

    def _timeline_store(self):
        path = getattr(self.server, "timeline_path", None)
        if path is None:
            raise ValueError("Timeline store is not configured.")
        path.parent.mkdir(parents=True, exist_ok=True)
        graph = getattr(self.server, 'form_graph', None)
        return TimelineStore(path, form_graph_path=graph.path if graph else None)

    def _book_root(self):
        return Path(getattr(self.server,'books_dir',REPO_ROOT / 'books')).resolve()

    def _episode_commands(self, timeline, *, background=False):
        from prose_engine.episode_commands import EpisodeCommands
        def junctions():
            return self._form_store(timeline=timeline).junctions() if timeline.scope()['kind']=='afm-starters' else {}
        def schedule(operation):
            threading.Thread(target=operation,daemon=True).start()
        def legacy_source(episode):
            if timeline.scope()['kind']=='afm-starters' and episode=='spring-break' and DEFAULT_NOVEL.exists():
                return DEFAULT_NOVEL.read_text(encoding='utf-8')
        return EpisodeCommands(timeline,junctions=junctions,form_graph=self._form_store(timeline=timeline),
                               books_root=self._book_root(),provider_factory=getattr(self.server,'test_writer_factory',None),
                               schedule=schedule if background else None, legacy_source=legacy_source)

    def _timeline_view(self, timeline):
        from prose_engine.episode_commands import EpisodeCommands
        state = EpisodeCommands(timeline).execute('timeline.catalog', {'details':True})
        return {'cards':state['cards'], 'archived_cards':state['archived_cards'],
                'branches':state['branch_records'], 'scope':state['workspace'], 'history':state['history']}

    def _book_policy(self):
        from prose_engine.influence import load_influence
        from prose_engine.reference_policy import PolicyEditor
        root=self._book_root()
        manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        books=manifest.get('books')
        if not isinstance(books,list): raise ValueError('Book manifest is invalid')
        metadata=[{'source_id':book['slug']} for book in books
                  if isinstance(book,dict) and isinstance(book.get('slug'),str) and book['slug']]
        from prose_engine.library_indexes import quality_exclusions
        quality=quality_exclusions(root)
        titles={book['slug']:book.get('title',book['slug']) for book in books if isinstance(book,dict) and 'slug' in book}
        result=PolicyEditor(root).snapshot(metadata,load_influence(root))
        for source in result['sources']:
            source['title']=titles.get(source['id'],source['id'])
            source['quality_exclusion']=quality.get(source['id'])
        return result

    def do_GET(self):
        url = urlparse(self.path)
        if self._media_get(url):
            return
        if url.path == '/api/form-attachment':
            try:
                query=parse_qs(url.query); ident=query.get('id',[''])[0]
                if getattr(self.server,'timeline_only',False): self._timeline_store().get_episode(query.get('episode',[''])[0])
                meta,content=self._form_store().attachment(ident)
                preview = query.get('preview', [''])[0] == '1'
                image_type = attachment_image_type(content) if preview else None
                if preview and not image_type:
                    self._form_json(415, {'error': 'This file is available as a download.'})
                    return
                self.send_response(200)
                self.send_header('Content-Type', image_type or 'application/octet-stream')
                self.send_header('Content-Disposition', ("inline" if preview else "attachment") +
                                 "; filename*=UTF-8''" + quote(meta['name'],safe=''))
                self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
            except (ValueError,sqlite3.Error,OSError): self._form_json(404,{'error':'Attachment not found.'})
            return
        if url.path in ('/scene-fragments', '/scene-replay', '/scene-minds', '/scene-clips', '/scene-branches', '/mind-inspector'):
            episode = parse_qs(url.query).get('episode', [getattr(self.server, 'initial_episode', None)])[0]
            try:
                self._timeline_store().get_episode(episode)
                page = {'/scene-fragments':'scene_fragments_page.html','/scene-replay':'scene_replay_page.html',
                        '/scene-minds':'scene_minds_page.html','/scene-clips':'scene_clips_page.html',
                        '/scene-branches':'scene_branches_page.html','/mind-inspector':'mind_inspector_page.html'}[url.path]
                body = (REPO_ROOT/'tools'/page).read_bytes()
            except (ValueError, OSError, sqlite3.Error):
                self._form_json(404, {'error': 'Open a saved episode to inspect its scene graphs.'})
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
            return
        if url.path == '/fx06':
            try:
                from story_graph.fx06_scene import read
                with self._timeline_store()._connect() as c:
                    if read(c) is None:
                        raise ValueError('Open the FX06 pilot workspace')
                body=(REPO_ROOT/'tools/fx06_page.html').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type','text/html; charset=utf-8')
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                self.wfile.write(body)
            except (ValueError, OSError, sqlite3.Error):
                self._form_json(404,{'error':'The FX06 pilot is only installed in its own workspace.'})
            return
        if getattr(self.server, "timeline_only", False):
            query = parse_qs(url.query)
            scoped = bool(query.get("episode"))
            wants_legacy = url.path == "/legacy" or query.get("legacy", [""])[0] == "1"
            if url.path in ("/", "/index.html") and not wants_legacy:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.end_headers()
                self.wfile.write((REPO_ROOT / "tools/v2_page.html").read_bytes())
                return
            if wants_legacy and not scoped and url.path in ("/", "/index.html", "/legacy"):
                episode = getattr(self.server, "initial_episode", None)
                self.send_response(303)
                self.send_header("Location", "/legacy?" + urlencode({"episode": episode}) if episode else "/timeline")
                self.end_headers()
                return
            if (url.path.startswith("/api/") and url.path not in ("/api/timeline","/api/book-policy","/api/book-status","/api/cook/status","/api/writers","/api/sample-projects") and
                    not (url.path == "/api/beat-map" and scoped) and
                    not (url.path in ("/api/state", "/api/episode-context", "/api/form-graph") and scoped)) or url.path in ("/reader", "/foxy_mo2_reader.html", "/hot_scoomp_reader.html"):
                self._form_json(404, {"error": "Open an episode in the timeline."})
                return
        if url.path == '/api/cook/status':
            query = parse_qs(url.query)
            job_id = query.get('job_id', [''])[0]
            episode = query.get('episode', [''])[0]
            with _COOK_JOBS_LOCK:
                if not job_id and episode:
                    job_id = _COOK_LATEST_BY_EPISODE.get(episode, '')
                job = dict(_COOK_JOBS[job_id]) if job_id in _COOK_JOBS else None
            if job is None:
                self._form_json(404, {'error': 'Cook job not found.'})
            else:
                self._form_json(200, job)
            return
        if url.path == '/api/beat-map':
            from story_graph.beat_map import map_episode
            try:
                query=parse_qs(url.query)
                self._form_json(200,map_episode(self._timeline_store(),query['episode'][0],int(query['revision'][0]),viewpoint=query.get('viewpoint',[''])[0] or None))
            except (ValueError,KeyError,TypeError,sqlite3.Error,OSError) as exc:
                self._form_json(400,{'error':str(exc)})
            return
        if url.path == '/api/book-policy':
            try: self._form_json(200,self._book_policy())
            except (OSError,ValueError,TypeError,KeyError) as exc: self._form_json(400,{'error':str(exc)})
            return
        if url.path == '/api/writers':
            from prose_engine.providers.session_registry import session_names
            try:
                self._form_json(200,{'writers':[{'id':mode,'label':label} for mode,label in session_names().items()]})
            except (OSError,ValueError,TypeError,KeyError):
                self._form_json(503,{'error':'Writer configuration is unavailable.'})
            return
        if url.path == '/api/book-status':
            from prose_engine.library_indexes import library_status
            from prose_engine.providers.session_registry import session_names
            try:
                query=parse_qs(url.query);backend=query.get('backend',['none'])[0];provider=query.get('provider',['codex-session'])[0]
                if provider not in session_names() or backend not in ('none','topic','luar','style'):
                    raise ValueError('Invalid book source or session')
                if backend=='none':
                    self._form_json(200,{'state':'disabled','message':'Book references are disabled.','generation_started':False})
                else:
                    status=library_status(self._book_root(),provider)
                    selected=status['indexes'][backend]
                    self._form_json(200,{**status,'backend':backend,'state':selected['state'],'message':selected['message']})
            except (OSError,ValueError,TypeError,KeyError) as exc: self._form_json(400,{'error':str(exc)})
            return
        if url.path == '/api/sample-projects':
            sample_dir = STUDIO_ASSETS_DIR / 'sample_projects'
            index_path = sample_dir / 'index.json'
            projects = []
            if index_path.exists():
                index_data = json.loads(index_path.read_text(encoding='utf-8'))
                for item in index_data.get('projects', []):
                    pfile = sample_dir / str(item.get('file', ''))
                    if pfile.exists():
                        projects.append(json.loads(pfile.read_text(encoding='utf-8')))
            self._form_json(200, {'projects': projects})
            return
        from tools.studio_canon_routes import serve_v2_asset
        if serve_v2_asset(self, url.path, STUDIO_ASSETS_DIR):
            return
        if url.path == "/assets/compose_blocks.js":
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.end_headers()
            self.wfile.write((REPO_ROOT / "tools/compose_blocks.js").read_bytes())
            return
        if url.path == "/assets/noir-racing-reference.png":
            reference = REPO_ROOT / "docs/noir-ui-gap-report-assets-2026-11-09/racing-user-reference.png"
            if reference.is_file() and not reference.is_symlink():
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(reference.read_bytes())
                return
        if url.path == "/racing-comparison":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write((REPO_ROOT / "tools/racing_compare.html").read_bytes())
            return
        if url.path == "/graph-comparison":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write((REPO_ROOT / "tools/character_graph_comparison.html").read_bytes())
            return
        if url.path in ("/assets/noir-character-graph-concept.png", "/assets/noir-character-graph-overview.png", "/assets/noir-track-loader.gif", "/assets/noir-racing-track.png", "/assets/noir-track-dial-frames.png", "/assets/noir-track-dial-25-once.gif", "/assets/noir-track-dial-50-once.gif", "/assets/noir-track-dial-75-once.gif", "/assets/noir-track-dial-100-once.gif"):
            asset = REPO_ROOT / "tools" / "assets" / Path(url.path).name
            if asset.is_file() and not asset.is_symlink():
                self.send_response(200)
                self.send_header("Content-Type", "image/gif" if asset.suffix == ".gif" else "image/png")
                self.end_headers()
                self.wfile.write(asset.read_bytes())
                return
        if url.path == "/world-laws":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write((REPO_ROOT / "tools/world_laws_page.html").read_bytes())
            return
        if url.path in ("/v2", "/v2/"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write((REPO_ROOT / "tools/v2_page.html").read_bytes())
            return
        if url.path == "/timeline":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write((REPO_ROOT / "tools/timeline_page.html").read_bytes())
            return
        if url.path == "/api/timeline":
            try:
                self._form_json(200, self._timeline_view(self._timeline_store()))
            except (OSError, ValueError, sqlite3.Error):
                self._form_json(500, {"error": "Unable to open the timeline store."})
            return
        if url.path in ("/api/episode-context", "/api/state") and "episode" in parse_qs(url.query):
            try:
                query = parse_qs(url.query)
                episode_id = query["episode"][0]
                beat = int(query.get("beat", ["0"])[0])
                viewpoint = query.get("viewpoint", [None])[0]
                store = self._timeline_store()
                episode = store.get_episode(episode_id)
                events = store.resolve(episode_id, beat, viewpoint)
                if url.path == "/api/episode-context":
                    self._form_json(200, {"episode": episode_id, "beat": beat, "viewpoint": viewpoint,
                                          "scope":store.scope(), "events": events, "prerequisites": store.prerequisites(episode_id)})
                    return
                graph = episode["graph"]
                nodes = []
                for idx, node in enumerate(graph["nodes"]):
                    if not isinstance(node, dict) or not isinstance(node.get("id"), str):
                        raise ValueError("Episode graph has an invalid node")
                    nodes.append({**node, "title": node.get("title", node["id"]), "type": node.get("type", "episode"),
                                  "data": node.get("data") or {}, "inputs": node.get("inputs") or [],
                                  "outputs": node.get("outputs") or [], "x": node.get("x", 80 + idx * 250),
                                  "y": node.get("y", 120)})
                edges = graph["edges"]
                if any(not isinstance(e, dict) or not isinstance(e.get("from"), str) or not isinstance(e.get("to"), str) for e in edges):
                    raise ValueError("Episode graph has an invalid edge")
                text = episode["script"]
                legacy = store.scope()['kind'] == 'afm-starters' and episode_id == "spring-break" and episode["head"] == 0 and not text and not nodes
                if legacy:
                    text = DEFAULT_NOVEL.read_text(encoding="utf-8") if DEFAULT_NOVEL.exists() else ""
                    nodes, edges = DEFAULT_NODES, DEFAULT_CONNECTIONS
                paragraphs = text.split("\n\n") if legacy else ([text] if text else [])
                blocks = [{"id": f"block_{i}", "index": i, "text": p, "speaker": None,
                           "freeze": 100 if legacy else 0, "strength": "skip" if legacy else "standard"}
                          for i, p in enumerate(paragraphs) if p.strip()]
                from story_graph.source_imports import binding, source_junctions
                from prose_engine.intake import saved_brief
                imported_source=None
                with store._connect() as c:
                    intake = saved_brief(c,episode_id)
                    found=binding(c,episode_id)
                    if found:
                        link,payload=found
                        imported_source={'edition':payload['edition'],'source_line':next(s['line'] for s in payload['sections'] if s['start']==link['start']),
                            'status':'historical source graph; not approved canon or a live character mind',
                            'canon_leaks':len(payload['diagnostics']['canon_leaks']),'unresolved_cues':len(payload['diagnostics']['unresolved_cues']),
                            'characters':{cid:{'label':g.forms[0].label,'forms':{f.id:f.label for f in g.forms}} for cid,g in source_junctions(payload).items()}}
                self._form_json(200, {"nodes": nodes, "connections": edges, "blocks": blocks,
                                      "imported_source":imported_source, "intake":intake,
                                      "episode": episode, "scope": store.scope(), "legacy_locked": legacy, "script_text": text,
                                      "context": events, "prerequisites": store.prerequisites(episode_id)})
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
                self._form_json(400, {"error": str(exc)})
            return
        if url.path == "/api/form-graph":
            try:
                if getattr(self.server, 'timeline_only', False):
                    self._timeline_store().get_episode(parse_qs(url.query)['episode'][0])
                episode = parse_qs(url.query).get('episode', [None])[0]
                payload = self._form_view(self._form_store(episode).read(), episode)
            except (sqlite3.Error, ValueError, KeyError, OSError):
                self._form_json(500, {"error": "Could not open the local character graph store."})
            else:
                self._form_json(200, payload)
            return
        if url.path in ("/", "/index.html", "/legacy"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
            return

        if url.path.startswith("/vendor/"):
            fname = url.path.split("/vendor/", 1)[1]
            vendor_file = REPO_ROOT / "tools" / "vendor" / fname
            if Path(fname).name == fname and vendor_file.is_file() and not vendor_file.is_symlink():
                ctype = "application/javascript; charset=utf-8" if fname.endswith(".js") else "text/css; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.end_headers()
                self.wfile.write(vendor_file.read_bytes())
                return

        if url.path.startswith("/images/"):
            fname = url.path.split("/images/", 1)[1]
            img_file = getattr(self.server, 'images_dir', REPO_ROOT / 'work/americandad/foxy_mo2_images') / fname
            types = {'.png':'image/png','.jpeg':'image/jpeg','.jpg':'image/jpeg','.webp':'image/webp'}
            ctype = types.get(img_file.suffix.lower())
            if ctype and Path(fname).name == fname and img_file.is_file() and not img_file.is_symlink():
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(img_file.read_bytes())
                return

        if url.path in ["/reader", "/foxy_mo2_reader.html", "/hot_scoomp_reader.html"]:
            reader_file = REPO_ROOT / "work/americandad/foxy_mo2_reader.html"
            if reader_file.exists():
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(reader_file.read_bytes())
                return

        if url.path == "/api/state":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()

            blocks = []
            if self.novel_path.exists():
                text = self.novel_path.read_text(encoding="utf-8")
                raw_paras = [p.strip() for p in text.split("\n\n") if p.strip()]

                for idx, p in enumerate(raw_paras):
                    speaker = None
                    has_quote = ('"' in p or '“' in p or '”' in p)

                    # Transformation state: Peter Griffin variant
                    if any(kw in p for kw in ["Rainee-Peter", "Peter-bear", "Peter Griffin"]) or (idx >= 65 and idx <= 90 and any(kw in p for kw in ["Hehehe", "kill zone", "cleft butt-chin", "sweet merciful Jesus", "whoops", "rusty lawnmower"])):
                        speaker = "RAINEE (PETER)"
                    # Transformation state: Nurse Pamela Franny Anderson
                    elif any(kw in p for kw in ["Nurse Pamela", "Pamela Franny", "Dr. Franny", "paramedic training"]):
                        speaker = "NURSE FRANNY ANDERSON"
                    # Roger the Alien (Scene 7 & driveway)
                    elif idx >= 115 and any(kw in p for kw in ["Roger", "ROGER", "Rutgers", "butt plug", "motel off the freeway", "goody bags", "royal ermine", "diamond tennis bracelets", "taking the girls"]):
                        speaker = "ROGER"
                    # Base characters
                    elif any(name in p for name in ["FRANCINE", "Francine"]) and has_quote:
                        speaker = "FRANCINE"
                    elif any(name in p for name in ["HALEY", "Haley"]) and has_quote:
                        speaker = "HALEY"
                    elif any(name in p for name in ["RAINEE", "Rainee"]) and has_quote:
                        speaker = "RAINEE"
                    elif any(name in p for name in ["STELLA", "Stella"]) and has_quote:
                        speaker = "STELLA"
                    elif any(name in p for name in ["ROGER", "Roger"]) and has_quote:
                        speaker = "ROGER"

                    blocks.append({
                        "id": f"block_{idx}",
                        "index": idx,
                        "text": p,
                        "speaker": speaker,
                        "freeze": 100 if speaker else 0,
                        "strength": "standard" if not speaker else "skip"
                    })

            payload = {
                "nodes": DEFAULT_NODES,
                "connections": DEFAULT_CONNECTIONS,
                "blocks": blocks,
            }
            try:
                payload["character_junctions"] = self._form_store().read()["junctions"]
            except (sqlite3.Error, ValueError, KeyError, OSError):
                payload["character_junctions"] = []
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            return

        self.send_error(404, "Not Found")

    def do_POST(self):
        url = urlparse(self.path)
        if self._media_post(url):
            return
        if getattr(self.server, "timeline_only", False) and url.path not in ("/api/scoped", "/api/beat-group", "/api/beat-anchors", "/api/timeline", "/api/notebook", "/api/drafts", "/api/world-laws", "/api/canon-diff", "/api/canon-proposals", "/api/slot-infill", "/api/craft-brief", "/api/book-policy", "/api/character-profiles", "/api/beat-rhythm", "/api/form-graph", "/api/cook", "/api/episode-command", "/api/intake", "/api/word-prep"):
            self._form_json(404, {"error": "Use the actions in an open timeline episode."})
            return
        if url.path in ('/api/episode-command','/api/intake','/api/word-prep'):
            from story_graph.scene_fragments import SceneFragmentError
            try:
                from prose_engine.intake import MAX_REQUEST
                if self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':
                    self._form_json(403,{'error':'Open the episode in this Studio window.'});return
                length=int(self.headers.get('Content-Length','0'))
                limit = {'/api/intake': MAX_REQUEST, '/api/word-prep': 1_000_000}.get(url.path, 100_000)
                if (not 0 < length <= limit or self.headers.get_content_type()!='application/json'
                        or self.headers.get('Transfer-Encoding') is not None):
                    raise ValueError('Invalid episode command request')
                req=json.loads(self.rfile.read(length).decode('utf-8'))
                if url.path == '/api/intake' and req['action'] not in (
                        'intake.preview','intake.create','intake.receipt','intake.source','episode.create','intake.plan','intake.launch','intake.history'):
                    raise ValueError('Choose a document or episode creation action.')
                if url.path == '/api/word-prep':
                    req['action'] = 'word_prep.promote'
                result=self._episode_commands(self._timeline_store(),background=True).execute(req['action'],req)
                self._form_json(200,result)
            except SceneFragmentError as exc:
                self._form_json(400, {'error': str(exc), 'code': exc.code})
            except SessionAttemptError as exc:
                self._form_json(409, {'error':str(exc), 'state':exc.state, 'attempt_id':exc.attempt_id})
            except BudgetExceeded as exc:
                self._form_json(429, {'error':str(exc), 'state':'budget_exhausted'})
            except ReferenceUnavailable as exc:
                self._form_json(409, {'error':str(exc), 'state':exc.state})
            except (ValueError,KeyError,TypeError,sqlite3.Error,OSError) as exc:
                self._form_json(400,{'error':str(exc)})
            return
        if url.path == '/api/cook':
            from prose_engine.cook import prepare_episode
            try:
                if self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':
                    self._form_json(403, {'error': 'Open the episode in this Studio window.'})
                    return
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 100_000 or self.headers.get_content_type() != 'application/json':
                    raise ValueError('Invalid cook request')
                req = json.loads(self.rfile.read(length).decode('utf-8'))
                episode = str(req.get('episode') or '').strip()
                if not episode:
                    raise ValueError('Episode is required')
                viewpoint = str(req.get('viewpoint') or '').strip() or None
                sync_mode = bool(req.get('sync', False))
                timeline = self._timeline_store()
                form_store = getattr(self.server, 'form_graph', None)
                current_head = timeline.get_episode(episode)['head']
                expected_head = req.get('timeline_revision', current_head)
                if type(expected_head) is not int or expected_head != current_head:
                    raise ValueError('Episode changed; reload the saved draft before preparing it')
                notebook_head = req.get('notebook_revision')

                job_id = uuid.uuid4().hex[:12]
                initial_stages = [
                    {'id': 'split', 'label': 'Type manuscript blocks', 'status': 'pending', 'detail': 'Waiting'},
                    {'id': 'graph', 'label': 'Resolve character sockets', 'status': 'pending', 'detail': 'Waiting'},
                    {'id': 'beat', 'label': 'Save scene graphs and beats', 'status': 'pending', 'detail': 'Waiting'},
                ]
                job_record = {
                    'job_id': job_id,
                    'episode': episode,
                    'status': 'running',
                    'stage_index': 1,
                    'progress': 8,
                    'message': 'Preparing the saved episode…',
                    'stages': initial_stages,
                    'result': None,
                    'error': None,
                    'started_at': time.time(),
                    'finished_at': None,
                }
                with _COOK_JOBS_LOCK:
                    _COOK_JOBS[job_id] = job_record
                    _COOK_LATEST_BY_EPISODE[episode] = job_id

                def _progress_cb(stage_idx: int, pct: int, st: str, detail: str) -> None:
                    with _COOK_JOBS_LOCK:
                        j = _COOK_JOBS[job_id]
                        j['stage_index'] = stage_idx
                        j['progress'] = pct
                        j['message'] = detail
                        stages = [dict(s) for s in j['stages']]
                        if 1 <= stage_idx <= len(stages):
                            stages[stage_idx - 1]['status'] = st
                            stages[stage_idx - 1]['detail'] = detail
                        j['stages'] = stages

                def _execute_cook() -> dict:
                    try:
                        result = prepare_episode(timeline, {
                            **req, 'episode':episode, 'viewpoint':viewpoint,
                            'timeline_revision':expected_head, 'notebook_revision':notebook_head,
                        }, form_store=form_store, progress_cb=_progress_cb)
                        with _COOK_JOBS_LOCK:
                            j = _COOK_JOBS[job_id]
                            j['status'] = 'completed'
                            j['progress'] = 100
                            j['result'] = result
                            j['finished_at'] = time.time()
                            j['message'] = (
                                f"Saved {len(result['receipt']['fragments'])} scene graphs · "
                                f"{len(result['receipt']['sockets'])} character sockets used · "
                                f"{result['stage1']['blocks_after']} blocks"
                            )
                            return dict(j)
                    except Exception as exc:
                        with _COOK_JOBS_LOCK:
                            j = _COOK_JOBS[job_id]
                            j['status'] = 'failed'
                            j['error'] = str(exc)
                            j['finished_at'] = time.time()
                            j['message'] = str(exc)
                            return dict(j)

                if sync_mode:
                    final_job = _execute_cook()
                    self._form_json(200 if final_job['status'] == 'completed' else 500, final_job)
                else:
                    threading.Thread(target=_execute_cook, daemon=True).start()
                    with _COOK_JOBS_LOCK:
                        self._form_json(202, dict(_COOK_JOBS[job_id]))
            except (ValueError, KeyError, TypeError, sqlite3.Error, OSError) as exc:
                self._form_json(400, {'error': str(exc)})
            return
        if url.path == '/api/beat-anchors':
            from story_graph.beat_anchors import BeatAnchorStore
            try:
                if self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':
                    self._form_json(403,{'error':'Open the episode in this Studio window.'});return
                length=int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 100_000 or self.headers.get_content_type() != 'application/json':
                    raise ValueError('Invalid anchor request')
                req=json.loads(self.rfile.read(length).decode('utf-8'))
                timeline=self._timeline_store()
                from story_graph.universe_scope import verify_scope
                with timeline._connect() as c:verify_scope(c,project_id=req.get('project'),universe_id=req.get('universe'))
                anchors=BeatAnchorStore(timeline)
                if req.get('action')=='open':result=anchors.open(req['episode'],req['revision'],viewpoint=req.get('viewpoint') or None)
                else:result=anchors.change(req.get('action'),req)
                self._form_json(200,result)
            except (ValueError,KeyError,TypeError,sqlite3.Error,OSError) as exc:
                self._form_json(400,{'error':str(exc)})
            return
        if url.path == '/api/beat-rhythm':
            from story_graph.beat_rhythm import BeatRhythmStore
            from story_graph.universe_scope import verify_scope
            try:
                if self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':
                    self._form_json(403,{'error':'Open beat direction in this Studio window.'});return
                length=int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 65536 or self.headers.get_content_type()!='application/json': raise ValueError('Invalid beat direction request')
                req=json.loads(self.rfile.read(length).decode('utf-8'));timeline=self._timeline_store()
                with timeline._connect() as c: verify_scope(c,project_id=req.get('project'),universe_id=req.get('universe'))
                rhythm=BeatRhythmStore(timeline);action=req.get('action')
                if action=='open':result=rhythm.open(req['episode'],req['beat'])
                elif action=='save':result=rhythm.save(req['episode'],req['beat'],req['timeline_revision'],req['revision'],req['profile'])
                elif action=='undo':result=rhythm.undo(req['episode'],req['beat'],req['timeline_revision'],req['revision'])
                elif action=='redo':result=rhythm.redo(req['episode'],req['beat'],req['timeline_revision'],req['revision'])
                elif action=='structure_open':
                    result=rhythm.open_structure(req['episode'],req['timeline_revision'],
                                                 beat_id=req.get('passage'),viewpoint=req.get('viewpoint'))
                elif action=='structure_save':
                    result=rhythm.save_structure(req['episode'], req['timeline_revision'], req['revision'],
                                                 req['preset'], beat_id=req.get('passage'), point=req.get('point'),
                                                 viewpoint=req.get('viewpoint'))
                else:raise ValueError('Unknown beat direction action')
                self._form_json(200,result)
            except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as exc:self._form_json(400,{'error':str(exc)})
            return
        if url.path == '/api/character-profiles':
            from story_graph.character_profiles import CharacterProfileStore
            from story_graph.universe_scope import verify_scope
            try:
                if self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':
                    self._form_json(403,{'error':'Open character profiles in this Studio window.'});return
                length=int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 1_000_000 or self.headers.get_content_type()!='application/json': raise ValueError('Invalid character profile request')
                req=json.loads(self.rfile.read(length).decode('utf-8'));timeline=self._timeline_store()
                with timeline._connect() as c: identity=verify_scope(c,project_id=req.get('project'),universe_id=req.get('universe'))
                if identity['kind']!='afm-starters': raise ValueError('No character form adapter is connected for this universe')
                profiles=CharacterProfileStore(timeline)
                if req.get('action')=='open':
                    result=profiles.open(req['character'],req['form'],req['node'])
                elif req.get('action')=='save':
                    result=profiles.save(req['character'],req['form'],req['node'],req['kind'],req['revision'],req['fields'],self._form_store().junctions())
                elif req.get('action')=='undo':
                    result=profiles.undo(req['character'],req['form'],req['node'],req['kind'],req['revision'],self._form_store().junctions())
                else: raise ValueError('Unknown character profile action')
                self._form_json(200,result)
            except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as exc: self._form_json(400,{'error':str(exc)})
            return
        if url.path == '/api/book-policy':
            from prose_engine.reference_policy import PolicyEditor
            try:
                if self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':
                    self._form_json(403,{'error':'Open book settings in this Studio window.'});return
                length=int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 65536 or self.headers.get_content_type()!='application/json': raise ValueError('Invalid book settings request')
                req=json.loads(self.rfile.read(length).decode('utf-8'))
                existing=self._book_policy()
                PolicyEditor(self._book_root()).update(req.get('source'),req.get('enabled'),req.get('permissions'),
                    req.get('revision'),{row['id'] for row in existing['sources']})
                self._form_json(200,self._book_policy())
            except (OSError,ValueError,TypeError,KeyError) as exc: self._form_json(400,{'error':str(exc)})
            return
        if url.path == '/api/world-laws':
            from story_graph.world_laws import WorldLawStore
            try:
                if self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':
                    self._form_json(403, {'error':'Open the episode in this Studio window.'}); return
                length=int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 1_000_000 or self.headers.get_content_type() != 'application/json':
                    raise ValueError('Invalid world law request')
                req=json.loads(self.rfile.read(length).decode('utf-8'))
                laws=WorldLawStore(self._timeline_store(),project_id=req.get('project'),universe_id=req.get('universe'))
                if req.get('action') == 'open': result=laws.open()
                elif req.get('action') == 'save': result=laws.save(req['revision'],req['laws'])
                elif req.get('action') == 'undo': result=laws.undo(req['revision'])
                elif req.get('action') == 'redo': result=laws.redo(req['revision'])
                else: raise ValueError('Unknown world law action')
                self._form_json(200,result)
            except (ValueError,KeyError,TypeError,sqlite3.Error,OSError) as exc:
                self._form_json(400,{'error':str(exc)})
            return
        if url.path in ('/api/canon-diff', '/api/canon-proposals', '/api/slot-infill', '/api/craft-brief'):
            self._handle_canon_endpoint(url.path)
            return
        if url.path in ('/api/notebook', '/api/drafts'):
            from prose_engine.notebook import NotebookStore, resolve, joined
            try:
                if self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':
                    self._form_json(403, {'error':'Open the episode in this Studio window.'})
                    return
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 6_000_000 or self.headers.get_content_type() != 'application/json':
                    raise ValueError('Invalid notebook request')
                req = json.loads(self.rfile.read(length).decode('utf-8'))
                timeline = self._timeline_store()
                from story_graph.universe_scope import verify_scope
                with timeline._connect() as c:
                    verify_scope(c,project_id=req.get('project'),universe_id=req.get('universe'))
                notebook = NotebookStore(timeline)
                action = req.get('action'); episode = req['episode']
                if url.path == '/api/notebook':
                    if action == 'open': result = notebook.open(episode)
                    elif action == 'current': result = {'notebook': notebook.existing(episode)}
                    elif action == 'protection':
                        state=notebook.existing(episode)
                        if state is None or state['stale']: raise ValueError('Notebook protection is missing or stale')
                        result={'revision':state['revision'],'ranges':resolve(joined(state['blocks']),state['default_protection'],state['masks'])}
                    elif action == 'save':
                        result = notebook.save(episode, req['revision'], req['timeline_revision'], req['blocks'], req['default_protection'], req['masks'])
                    elif action == 'split':
                        result = notebook.split(episode, req['revision'], req['timeline_revision'], req['block'], req['offset'])
                    elif action == 'merge':
                        result = notebook.merge(episode, req['revision'], req['timeline_revision'], req['first'], req['second'])
                    elif action == 'edit':
                        result = notebook.edit_text(episode, req['revision'], req['timeline_revision'], req['start'], req['end'], req['text'])
                    elif action == 'append-block':
                        result = notebook.append_block(episode, req['revision'], req['timeline_revision'], req['kind'], req.get('speaker'), junctions=self._form_store().junctions())
                    elif action == 'speaker-options':result=notebook.speaker_options(episode,req['block'])
                    elif action == 'bind-speaker':result=notebook.bind_speaker(episode,req['revision'],req['timeline_revision'],req['block'],req.get('character'),req.get('form'))
                    elif action == 'save-document': result = notebook.save_document(episode, req['revision'], req['timeline_revision'], req['text'], req['graph'])
                    elif action == 'dismiss-stale': result = notebook.dismiss_stale_mask(episode, req['revision'], req['timeline_revision'], req['mask'])
                    elif action == 'sync': result = notebook.sync(episode, req['revision'], req['timeline_revision'])
                    elif action in ('undo','redo'):
                        edit = self._episode_commands(timeline).execute('notebook.'+action,
                            {**req,'notebook_revision':req['revision']})
                        result = dict(edit['notebook'],edit_receipt=edit['receipt'],replayed=edit['status']=='REPLAYED')
                    else: raise ValueError('Unknown notebook action')
                else:
                    bindings = {'list':'draft.list', 'open':'draft.open', 'compare':'draft.compare',
                                'favorite':'draft.favorite', 'undo_favorite':'draft.favorite.undo',
                                'redo_favorite':'draft.favorite.redo'}
                    command = bindings.get(action.replace('-', '_')) if isinstance(action,str) else None
                    if command:
                        result = self._episode_commands(timeline).execute(command,
                            {**req, 'value':req.get('value',req.get('favorite'))})
                    elif action in ('use', 'keep-selection'):
                        edit = self._episode_commands(timeline).execute('draft.apply',
                            {**req,'notebook_revision':req['revision']})
                        result = dict(edit['notebook'],edit_receipt=edit['receipt'],replayed=edit['status']=='REPLAYED')
                    else: raise ValueError('Unknown draft action')
                self._form_json(200, result)
            except (ValueError, KeyError, TypeError, sqlite3.Error, OSError) as exc:
                self._form_json(400, {'error': str(exc)})
            return
        if url.path == '/api/beat-group':
            from prose_engine.beat_workflow import preview_group
            try:
                if self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':
                    self._form_json(403,{'error':'Open the episode in this Studio window.'});return
                length=int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 65536 or self.headers.get_content_type()!='application/json':
                    raise ValueError('Invalid beat group request')
                req=json.loads(self.rfile.read(length).decode('utf-8'));store=self._timeline_store()
                def junctions(): return self._form_store().junctions() if store.scope()['kind']=='afm-starters' else {}
                action=req.get('action','generate')
                if action not in ('preview','generate'): raise ValueError('Unknown beat group action')
                if action=='preview':
                    result=preview_group(store,req,junctions=junctions,books_root=self._book_root())
                else:
                    from prose_engine.notebook import NotebookStore
                    from story_graph.director import fingerprint
                    n=NotebookStore(store).existing(req['episode'])
                    if n is None:
                        raise ValueError('Save the notebook before generating a scene')
                    if req.get('rhythm_plan_id') is not None:
                        preview_group(store,req,junctions=junctions,books_root=self._book_root())
                    command=self._episode_commands(store)
                    run=command.execute('run.start',{**req,
                        'request_id':req.get('request_id') or 'legacy-'+fingerprint(req)[:32],
                        'notebook_revision':req.get('notebook_revision',n['revision'])})
                    draft=command.execute('draft.open',{'episode':run['episode'],'branch':run['branch'],
                            'draft':run['draft_id']}) if run['draft_id'] else None
                    result={'status':'PROPOSED' if run['status']=='COMPLETED' else run['status'],
                            'draft_id':run['draft_id'],'text':draft['text'] if draft else None,
                            'completed':[part for part in run['parts'] if part['status']=='PROPOSED'],
                            'error':run['reason'],'run':run}
                self._form_json(200,result)
            except (ValueError,KeyError,TypeError,sqlite3.Error,OSError) as exc:
                self._form_json(400,{'error':str(exc)})
            return
        if url.path == "/api/scoped":
            from prose_engine.scoped_service import execute_scoped
            try:
                if self.headers.get("Origin") != f"http://127.0.0.1:{self.server.server_port}":
                    self._form_json(403, {"error": "Open the episode in this Studio window."})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536 or self.headers.get_content_type() != "application/json":
                    raise ValueError("Invalid scoped request")
                req=json.loads(self.rfile.read(length).decode("utf-8"))
                store=self._timeline_store()
                def junctions():
                    return self._form_store().junctions() if store.scope()['kind']=='afm-starters' else {}
                def legacy():
                    return DEFAULT_NOVEL.read_text(encoding='utf-8') if store.scope()['kind']=='afm-starters' and req['episode']=='spring-break' and DEFAULT_NOVEL.exists() else None
                payload = (self._episode_commands(store).execute(req['action'], req) if req.get('action') in ('run.selection', 'run.selection.preview')
                           else execute_scoped(store,req.get('action'),req,junctions=junctions,legacy_source=legacy,
                                               books_root=self._book_root(),provider_factory=getattr(self.server,'test_writer_factory',None)))
                self._form_json(200,payload)
            except SessionAttemptError as exc:
                self._form_json(409,{"error":str(exc),"state":exc.state,"attempt_id":exc.attempt_id})
            except BudgetExceeded as exc:
                self._form_json(429,{"error":str(exc),"state":"budget_exhausted"})
            except ReferenceUnavailable as exc:
                self._form_json(409,{"error":str(exc),"state":exc.state})
            except (ValueError, KeyError, TypeError, sqlite3.Error, OSError) as exc:
                self._form_json(400,{"error":str(exc)})
            except Exception:
                self._form_json(502,{"error":"The selected session could not complete the request."})
            return
        if url.path == "/api/timeline":
            try:
                if self.headers.get("Origin") != f"http://127.0.0.1:{self.server.server_port}":
                    self._form_json(403, {"error": "Open the timeline in this Studio window."})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 6_000_000 or self.headers.get_content_type() != "application/json":
                    raise ValueError("Invalid timeline request.")
                req = json.loads(self.rfile.read(length).decode("utf-8"))
                store = self._timeline_store()
                from story_graph.universe_scope import verify_scope
                with store._connect() as c:
                    verify_scope(c,project_id=req.get('project'),universe_id=req.get('universe'))
                if req.get('action') in ('timeline.preview','timeline.move','timeline.rename','timeline.cover.set','timeline.archive','timeline.restore',
                                         'timeline.undo','timeline.redo'):
                    payload = self._episode_commands(store).execute(req['action'],req)
                elif req.get("action") == "events":
                    payload = {"events": store.episode_events(req["id"])}
                elif req.get("action") == "review_event":
                    store.review_event(req["episode"], req["event"], req["reviewer"], req["source_id"], req.get("permitted"))
                    payload = {"saved": True}
                elif req.get("action") == "starters":
                    store.add_starter_cards()
                    payload = {"cards": store.cards()}
                elif req.get("action") == "open":
                    payload = {"episode": store.get_episode(req["id"]), "scope": store.scope()}
                elif req.get("action") == "rejoin":
                    merged = store.rejoin(req["episode"], req["event"], req["target_episode"], req["beat"],
                                          req["reviewer"], req["source_id"], req.get("permitted"),
                                          rejoined_id=req.get("rejoined_event"))
                    payload = {"event": merged}
                elif req.get("action") == "unrejoin":
                    info = store.unrejoin(req["target_episode"], req["event"])
                    payload = {"unrejoined": info, "events": store.episode_events(req["target_episode"])}
                elif req.get("action") == "bind_form":
                    if store.scope()['kind'] != 'afm-starters':
                        raise ValueError('AFM character forms are not available in this universe')
                    store.bind_form_event(req["episode"], req["event"], req["character"], req["form"],
                                          req["form_action"], self._form_store().junctions())
                    payload = {"saved": True}
                elif req.get("action") == "unbind_form":
                    if store.scope()['kind'] != 'afm-starters':
                        raise ValueError('AFM character forms are not available in this universe')
                    res = store.unbind_form_event(req["episode"], req["event"])
                    payload = dict(res, saved=True)
                elif req.get("action") == "redo_form":
                    if store.scope()['kind'] != 'afm-starters':
                        raise ValueError('AFM character forms are not available in this universe')
                    res = store.redo_form_event(req["episode"], req["event"], junctions=self._form_store().junctions())
                    payload = dict(res, saved=True)
                elif req.get("action") == "event":
                    store.add_event(req["event"], req["episode"], req["beat"], req["content"],
                                    status=req.get("status", "draft"), permitted=req.get("permitted", False),
                                    viewpoint=req.get("viewpoint") or None, source_id=req.get("source_id", ""),
                                    reviewer=req.get("reviewer", ""))
                    payload = {"saved": True}
                elif req.get("action") == "unadd_event":
                    removed = store.unadd_event(req["episode"], req["event"])
                    payload = {"removed": removed, "events": store.episode_events(req["episode"])}
                elif req.get("action") == "restore_event":
                    junctions = self._form_store().junctions() if store.scope()['kind'] == 'afm-starters' else None
                    restored = store.restore_event(req["episode"], req["event"], junctions=junctions)
                    payload = {"restored": restored, "events": store.episode_events(req["episode"])}
                elif req.get("action") == "unreview_event":
                    res = store.unreview_event(req["episode"], req["event"], req.get("reviewer") or "Author")
                    payload = dict(res, saved=True)
                elif req.get("action") == "finish":
                    store.finish(req["id"], req["expected_revision"], req["reviewer"])
                    payload = {"episode": store.get_episode(req["id"])}
                elif req.get("action") == "reopen":
                    info = store.reopen(req["id"], expected_revision=req.get("expected_revision"))
                    payload = {"episode": store.get_episode(req["id"]), "reopened": info}
                elif req.get("action") == "fork":
                    store.fork(req["branch"], req["parent"], req["episode"], req["beat"])
                    payload = {"branches": store.branches()}
                elif req.get("action") == "unfork":
                    removed = store.unfork(req["branch"])
                    payload = {"branches": store.branches(), "unforked": removed}
                elif req.get("action") == "create":
                    store.create_episode(req["id"], req["title"], req.get("branch", "main"), req["position"], req.get("cover"), after=req.get("after"))
                    payload = {"episode": store.get_episode(req["id"])}
                elif req.get("action") in ("undo_history", "redo_history"):
                    action = 'timeline.undo' if req["action"]=="undo_history" else 'timeline.redo'
                    res = self._episode_commands(store).execute(action,req)
                    payload = {**res, **self._timeline_view(store)}
                elif req.get("action") in ("archive", "restore"):
                    store.set_archived(req["id"], req["expected_revision"], req["action"] == "archive")
                    payload = {"cards": store.cards(), "archived_cards": store.archived_cards()}
                elif req.get("action") == "set_cover":
                    changed = store.set_cover(req["id"], req["expected_revision"], req["expected_cover"], req["cover"])
                    payload = {"changed": changed, "cover_history": store.cover_history_state(req["id"]), "episode": store.get_episode(req["id"])}
                elif req.get("action") == "undo_cover":
                    expected_cover = req["expected_cover"] if "expected_cover" in req else "__UNSET__"
                    res = store.undo_cover(req["id"], req.get("expected_revision"), expected_cover)
                    payload = dict(res, episode=store.get_episode(req["id"]), cards=store.cards())
                elif req.get("action") == "redo_cover":
                    expected_cover = req["expected_cover"] if "expected_cover" in req else "__UNSET__"
                    res = store.redo_cover(req["id"], req.get("expected_revision"), expected_cover)
                    payload = dict(res, episode=store.get_episode(req["id"]), cards=store.cards())
                elif req.get("action") == "move":
                    cards = store.move_episode(
                        req["id"],
                        req["expected_revision"],
                        after=req.get("after"),
                        direction=req.get("direction"),
                        position=req.get("position"),
                    )
                    payload = {"cards": cards, "episode": store.get_episode(req["id"]), "scope": store.scope()}
                elif req.get("action") == "save":
                    rev = store.save(req["id"], req["expected_revision"], graph=req.get("graph"),
                                     script=req.get("script"), source_name=req.get("source_name"), preserve_notebook=True)
                    payload = {"revision": rev}
                else:
                    raise ValueError("Unknown timeline action.")
                payload.setdefault("history", store.history_state())
                self._form_json(200, payload)
            except (ValueError, KeyError, TypeError, sqlite3.IntegrityError) as exc:
                self._form_json(400, {"error": str(exc)})
            except (OSError, sqlite3.Error):
                self._form_json(500, {"error": "Unable to save the timeline."})
            return
        if url.path == "/api/form-graph":
            try:
                if self.headers.get("Origin") != f"http://127.0.0.1:{self.server.server_port}":
                    self._form_json(403, {"error": "Open the character graph in this Studio window."})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 28_000_000 or self.headers.get_content_type() != "application/json":
                    raise ValueError("Invalid character graph request.")
                request = json.loads(self.rfile.read(length).decode("utf-8"))
                if getattr(self.server, 'timeline_only', False):
                    self._timeline_store().get_episode(request['episode'])
                if request.get('action') in ('stage_form', 'set_relationship'):
                    saved = self._timeline_store().get_episode(request.get('episode'))
                    if request.get('branch') != saved['branch']:
                        raise ValueError('The episode branch changed. Reload the graph.')
                    request.update(_episode_position=saved['position'],
                                   _time_travel_override=bool(saved.get('time_travel_override')))
                if (getattr(self.server,'timeline_only',False) and request.get('action') in ('undo_graph','redo_graph')
                        and self._timeline_store().scope()['kind']=='afm-starters'):
                    command = 'graph.undo' if request['action']=='undo_graph' else 'graph.redo'
                    result = self._episode_commands(self._timeline_store()).execute(command,request)
                else:
                    path = getattr(self.server, 'timeline_path', None)
                    result = self._form_store(request.get('episode')).change(
                        request, _history_path=path if path and Path(path).is_file() else None)
                payload = self._form_view(result, request.get('episode'))
            except StaleFormGraph as exc:
                self._form_json(409, {"error": str(exc)})
            except ValueError as exc:
                self._form_json(400, {"error": str(exc)})
            except (sqlite3.Error, KeyError, OSError):
                self._form_json(500, {"error": "The character graph could not be saved."})
            else:
                self._form_json(200, payload)
            return
        if url.path == "/api/scrub":
            from prose_engine.voice.slop import surgical_scrub
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length).decode("utf-8")
            data = json.loads(raw_body)
            blocks = data.get("blocks", [])

            all_actions = []
            cleaned_blocks = []
            for b in blocks:
                t = b.get("text", "")
                # Only scrub narration, preserve quoted dialogue verbatim
                cleaned_text, acts = surgical_scrub(t)
                if acts:
                    all_actions.extend([f"¶{b.get('index', '?')}: {a}" for a in acts])
                b_copy = dict(b)
                b_copy["text"] = cleaned_text
                cleaned_blocks.append(b_copy)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            resp = {
                "success": True,
                "blocks": cleaned_blocks,
                "actions": all_actions
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return
        if url.path == "/api/editorial":
            from prose_engine.editorial_adapter import dispatch
            from prose_engine.editorial_revisions import RevisionStore
            try:
                expected_origin = f"http://127.0.0.1:{self.server.server_port}"
                if self.headers.get("Origin") != expected_origin:
                    raise ValueError("invalid request origin")
                if self.review_store_path is None:
                    raise ValueError("start Studio with --review-store pointing to an existing revision store")
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1024 * 1024:
                    raise ValueError("invalid request size")
                request = json.loads(self.rfile.read(length).decode("utf-8"))
                result = dispatch(RevisionStore(self.review_store_path), WorldState.load(), request)
                status = 200
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
                result, status = {"error": str(exc)}, 400
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            return
        if url.path == "/api/compute":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            blocks = data.get("blocks", [])
            full_text = "\n\n".join(b.get("text", "") for b in blocks)
            score = ProseDiagnosticsAnalyzer.analyze(full_text).burstiness_score
            resp = {"success": True, "blocks": blocks, "burstiness": round(score, 2),
                    "accepted": 0, "rejected": 0, "status": "NO_PROPOSALS"}
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return

        self.send_error(404, "Not Found")

    def _handle_canon_endpoint(self, path: str) -> None:
        from tools.studio_canon_routes import handle_canon_endpoint
        handle_canon_endpoint(self, path)


def run_server(port: int = 8765, novel_file: Optional[str] = None, review_store: Optional[str] = None,
               form_store: Optional[str] = None, *, timeline_path=None, timeline_only=False, initial_episode=None,
               books_dir=None, test_writer_factory=None, images_dir=None):
    StudioRequestHandler.review_store_path = Path(review_store).resolve() if review_store else None
    StudioRequestHandler.novel_path = Path(novel_file).resolve() if novel_file else DEFAULT_NOVEL

    server = ThreadingHTTPServer(("127.0.0.1", port), StudioRequestHandler)
    selected=None
    if not timeline_path and not novel_file:
        from prose_engine.source_migration import selected_workspace
        selected=selected_workspace(REPO_ROOT/'.app-steward/local/studio/active_workspace.json')
    local_forms = Path(timeline_path).resolve().parent/'character-forms.sqlite' if timeline_path else None
    path = Path(form_store).resolve() if form_store else (
        selected[0]/'character-forms.sqlite' if selected else
        local_forms if local_forms is not None else
        (DEFAULT_FORM_STORE if StudioRequestHandler.novel_path == DEFAULT_NOVEL else None)
    )
    server.form_graph = FormGraphStore(path, form_targets())
    server.timeline_path = Path(timeline_path).resolve() if timeline_path else (selected[0]/'timeline.sqlite' if selected else REPO_ROOT / ".app-steward/local/studio/episode-timeline.sqlite")
    server.books_dir = Path(books_dir).resolve() if books_dir else REPO_ROOT / 'books'
    server.images_dir = Path(images_dir).resolve() if images_dir else REPO_ROOT / 'work/americandad/foxy_mo2_images'
    server.timeline_only = timeline_only
    server.test_writer_factory = test_writer_factory
    server.initial_episode = initial_episode or (selected[1]['initial_episode'] if selected else None)
    print(f"Noir Studio running at http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Noir Fiction Engine Studio Workbench")
    parser.add_argument("--port", type=int, default=8765, help="Port to run server on")
    parser.add_argument("--file", type=str, default=None, help="Open a standalone manuscript instead of the timeline")
    parser.add_argument("--review-store", default=None, help="Existing local reviewed revision store")
    parser.add_argument("--form-store", default=None, help="Local character graph store for this workspace")
    parser.add_argument("--timeline", help="Timeline database (uses the project timeline by default)")
    parser.add_argument("--episode", help="Open this timeline episode")
    parser.add_argument("--books-dir", help="Book library directory for scoped references")
    parser.add_argument("--images-dir", type=Path, help="Existing local character portrait directory")
    args = parser.parse_args(argv)
    if args.file and (args.timeline or args.episode):
        parser.error("--file is standalone; use --timeline and --episode for timeline work")
    if args.images_dir and not args.images_dir.is_dir():
        parser.error("--images-dir must be an existing portrait directory")
    run_server(port=args.port, novel_file=args.file, review_store=args.review_store, form_store=args.form_store,
               timeline_path=args.timeline, timeline_only=not args.file, initial_episode=args.episode,
               books_dir=args.books_dir, images_dir=args.images_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
