"""Same-origin Studio handlers for /api/canon-diff and /api/canon-proposals."""
from __future__ import annotations

import json
import sqlite3

from prose_engine.canon_guard import _merge_conn_state, compile_afm_state, resolve_episode_position
from prose_engine.fact_extractor import run_canon_passes
from prose_engine.slot_infill import apply_slot_fills, plan_infill_slots, validate_infill_seams
from story_graph.canon_models import StoryCoord
from story_graph.seeds.afm_seed import seed_afm_universe
from story_graph.state_compiler import (
    CANON_SCHEMA_SQL,
    StateCompiler,
    ensure_canon_schema,
    list_proposals,
    propose_canon_change,
    resolve_proposal,
    retire_delta,
)
from pathlib import Path
from story_graph.universe_scope import verify_scope

STUDIO_ASSET_MAP = {
    "/assets/studio_styles.css": ("studio_styles.css", "text/css; charset=utf-8"),
    "/assets/studio_client.js": ("studio_client.js", "application/javascript; charset=utf-8"),
    "/assets/studio_default_graph.json": ("studio_default_graph.json", "application/json; charset=utf-8"),
    "/assets/v2/tokens.css": ("v2/tokens.css", "text/css; charset=utf-8"),
    "/assets/v2/shell.css": ("v2/shell.css", "text/css; charset=utf-8"),
    "/assets/v2/compose.css": ("v2/compose.css", "text/css; charset=utf-8"),
    "/assets/v2/timeline.css": ("v2/timeline.css", "text/css; charset=utf-8"),
    "/assets/v2/graph.css": ("v2/graph.css", "text/css; charset=utf-8"),
    "/assets/v2/form-board.css": ("v2/form-board.css", "text/css; charset=utf-8"),
    "/assets/v2/beat.css": ("v2/beat.css", "text/css; charset=utf-8"),
    "/assets/v2/prose.css": ("v2/prose.css", "text/css; charset=utf-8"),
    "/assets/v2/intake.css": ("v2/intake.css", "text/css; charset=utf-8"),
    "/assets/v2/intake.js": ("v2/intake.js", "application/javascript; charset=utf-8"),
    "/assets/v2/shelf.css": ("v2/shelf.css", "text/css; charset=utf-8"),
    "/assets/v2/shelf.js": ("v2/shelf.js", "application/javascript; charset=utf-8"),
    "/assets/v2/analysis_lab.css": ("v2/analysis_lab.css", "text/css; charset=utf-8"),
    "/assets/v2/analysis_lab.js": ("v2/analysis_lab.js", "application/javascript; charset=utf-8"),
    "/assets/v2/desktop-host.js": ("v2/desktop-host.js", "application/javascript; charset=utf-8"),
    "/assets/v2/api.js": ("v2/api.js", "application/javascript; charset=utf-8"),
    "/assets/v2/store.js": ("v2/store.js", "application/javascript; charset=utf-8"),
    "/assets/v2/compose.js": ("v2/compose.js", "application/javascript; charset=utf-8"),
    "/assets/v2/splitter.js": ("v2/splitter.js", "application/javascript; charset=utf-8"),
    "/assets/v2/timeline.js": ("v2/timeline.js", "application/javascript; charset=utf-8"),
    "/assets/v2/story_timeline.js": ("v2/story_timeline.js", "application/javascript; charset=utf-8"),
    "/assets/v2/scene_plan.js": ("v2/scene_plan.js", "application/javascript; charset=utf-8"),
    "/assets/v2/graph_state.js": ("v2/graph_state.js", "application/javascript; charset=utf-8"),
    "/assets/v2/graph_engine.js": ("v2/graph_engine.js", "application/javascript; charset=utf-8"),
    "/assets/v2/graph_controller.js": ("v2/graph_controller.js", "application/javascript; charset=utf-8"),
    "/assets/v2/graph_canvas_view.js": ("v2/graph_canvas_view.js", "application/javascript; charset=utf-8"),
    "/assets/v2/graph.js": ("v2/graph.js", "application/javascript; charset=utf-8"),
    "/assets/v2/char_switchyard.css": ("v2/char_switchyard.css", "text/css; charset=utf-8"),
    "/assets/v2/char_switchyard.js": ("v2/char_switchyard.js", "application/javascript; charset=utf-8"),
    "/assets/v2/story_graph_canvas.css": ("v2/story_graph_canvas.css", "text/css; charset=utf-8"),
    "/assets/v2/story_graph_canvas.js": ("v2/story_graph_canvas.js", "application/javascript; charset=utf-8"),
    "/assets/v2/live_graph_bridge.js": ("v2/live_graph_bridge.js", "application/javascript; charset=utf-8"),
    "/assets/v2/form-board.js": ("v2/form-board.js", "application/javascript; charset=utf-8"),
    "/assets/v2/beat.js": ("v2/beat.js", "application/javascript; charset=utf-8"),
    "/assets/v2/prose.js": ("v2/prose.js", "application/javascript; charset=utf-8"),
    "/assets/v2/sound.js": ("v2/sound.js", "application/javascript; charset=utf-8"),
    "/assets/v2/vfx_engine.js": ("v2/vfx_engine.js", "application/javascript; charset=utf-8"),
    "/assets/v2/vfx_overlay.css": ("v2/vfx_overlay.css", "text/css; charset=utf-8"),
    "/assets/v2/app.js": ("v2/app.js", "application/javascript; charset=utf-8"),
    "/assets/v2/game-finish-plinth.webp": ("v2/game-finish-plinth.webp", "image/webp"),
    "/assets/v2/game-form-lab.webp": ("v2/game-form-lab.webp", "image/webp"),
    "/assets/v2/game-garage-entry.webp": ("v2/game-garage-entry.webp", "image/webp"),
    "/assets/v2/game-rule-marshal.webp": ("v2/game-rule-marshal.webp", "image/webp"),
    "/assets/v2/game-season-track.webp": ("v2/game-season-track.webp", "image/webp"),
    "/assets/v2/game-standby-pattern.webp": ("v2/game-standby-pattern.webp", "image/webp"),
    "/assets/v2/game-shutter-wipe.webp": ("v2/game-shutter-wipe.webp", "image/webp"),
    "/assets/v2/game-cook-ribbon.webp": ("v2/game-cook-ribbon.webp", "image/webp"),
    "/assets/v2/game-noir-logo.webp": ("v2/game-noir-logo.webp", "image/webp"),
    "/assets/v2/fx_bus.js": ("v2/fx_bus.js", "application/javascript; charset=utf-8"),
    "/assets/v2/history.js": ("v2/history.js", "application/javascript; charset=utf-8"),
    "/assets/v2/media_vault.js": ("v2/media_vault.js", "application/javascript; charset=utf-8"),
    "/assets/v2/world-paddock-canopy.webp": ("v2/world-paddock-canopy.webp", "image/webp"),
    "/assets/v2/world-sky-track.webp": ("v2/world-sky-track.webp", "image/webp"),
    "/assets/v2/world-coliseum-arena.webp": ("v2/world-coliseum-arena.webp", "image/webp"),
    "/assets/v2/world-starting-grid.webp": ("v2/world-starting-grid.webp", "image/webp"),
    "/assets/v2/world-turntable-garage.webp": ("v2/world-turntable-garage.webp", "image/webp"),
    "/assets/v2/audio/music/bgm_loop.mp3": ("v2/audio/music/bgm_loop.mp3", "audio/mpeg"),
    "/assets/v2/audio/sfx/sfx_hover.wav": ("v2/audio/sfx/sfx_hover.wav", "audio/wav"),
    "/assets/v2/audio/sfx/sfx_click.wav": ("v2/audio/sfx/sfx_click.wav", "audio/wav"),
    "/assets/v2/audio/sfx/sfx_latch.wav": ("v2/audio/sfx/sfx_latch.wav", "audio/wav"),
    "/assets/v2/audio/sfx/sfx_execute.wav": ("v2/audio/sfx/sfx_execute.wav", "audio/wav"),
    "/assets/v2/audio/sfx/sfx_complete.wav": ("v2/audio/sfx/sfx_complete.wav", "audio/wav"),
    "/assets/v2/audio/sfx/sfx_wipe.wav": ("v2/audio/sfx/sfx_wipe.wav", "audio/wav"),
    "/assets/v2/audio/sfx/sfx_alert.wav": ("v2/audio/sfx/sfx_alert.wav", "audio/wav"),
    "/assets/v2/audio/audio-manifest.json": ("v2/audio/audio-manifest.json", "application/json; charset=utf-8"),
    "/assets/v2/grand_prix/stage.webp": ("v2/grand_prix/stage.webp", "image/webp"),
    "/assets/v2/grand_prix/icons.svg": ("v2/grand_prix/icons.svg", "image/svg+xml; charset=utf-8"),
}


VFX_CONTENT_TYPES = {
    ".json": "application/json; charset=utf-8",
    ".lottie": "application/octet-stream",
    ".png": "image/png",
    ".webp": "image/webp",
    ".svg": "image/svg+xml; charset=utf-8",
    ".webm": "video/webm",
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
}


def _serve_contained_static(handler, root_dir: Path, rel: str) -> bool:
    if not rel or ".." in rel or "\\" in rel:
        return False
    base = root_dir.resolve()
    candidate = (base / rel).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return False
    ctype = VFX_CONTENT_TYPES.get(candidate.suffix.lower())
    if not ctype or not (candidate.is_file() and not candidate.is_symlink()):
        return False
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.end_headers()
    handler.wfile.write(candidate.read_bytes())
    return True


def serve_v2_asset(handler, url_path: str, assets_dir: Path) -> bool:
    """Serve static Studio v2 text/image assets from allowlisted STUDIO_ASSET_MAP, /blueprints/, /assets/audio/, or /assets/vfx/."""
    if url_path.startswith("/assets/audio/"):
        rel = url_path.removeprefix("/assets/audio/").lstrip("/")
        if "_extraction_workspace" in rel.split("/"):
            return False
        return _serve_contained_static(handler, assets_dir.parents[1] / "ui" / "assets" / "audio", rel)
    if url_path.startswith("/blueprints/"):
        rel = url_path.removeprefix("/blueprints/").lstrip("/")
        return _serve_contained_static(handler, assets_dir.parents[1] / "blueprints", rel)
    if url_path == "/assets/vfx/mockup_simulate_render.html":
        return _serve_contained_static(
            handler, assets_dir.parents[1] / "blueprints", "simulate_then_render/mockup_simulate_render.html"
        )
    if url_path.startswith("/assets/vfx/"):
        rel = url_path.removeprefix("/assets/vfx/").lstrip("/")
        return _serve_contained_static(handler, assets_dir.parents[1] / "ui" / "assets" / "vfx", rel)
    entry = STUDIO_ASSET_MAP.get(url_path)
    if not entry:
        return False
    filename, content_type = entry
    if filename.startswith("v2/"):
        relative = filename.removeprefix("v2/")
        ui_root = assets_dir.parents[1] / "ui"
        asset = (ui_root / "assets" if relative.startswith("audio/") else ui_root) / relative
    else:
        asset = assets_dir / filename
    if not (asset.is_file() and not asset.is_symlink()):
        return False
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.end_headers()
    handler.wfile.write(asset.read_bytes())
    return True


def handle_canon_endpoint(handler, path: str) -> None:
    """Validate same-origin JSON request and dispatch /api/canon-diff or /api/canon-proposals."""
    try:
        if handler.headers.get("Origin") != f"http://127.0.0.1:{handler.server.server_port}":
            raise PermissionError("Open canon tools in this Studio window.")
        length = int(handler.headers.get("Content-Length", "0"))
        if not 0 < length <= 1_000_000 or handler.headers.get_content_type() != "application/json":
            raise ValueError("Invalid canon JSON request")
        req = json.loads(handler.rfile.read(length).decode("utf-8"))
        timeline = handler._timeline_store()
        novel_path = getattr(handler, "novel_path", None)
        if path == "/api/canon-diff":
            result = run_canon_diff(timeline, req)
        elif path == "/api/canon-proposals":
            result = run_canon_proposals(timeline, req)
        elif path == "/api/slot-infill":
            result = run_slot_infill(timeline, req, novel_path=novel_path)
        elif path == "/api/craft-brief":
            result = run_craft_brief(timeline, req, novel_path=novel_path)
        else:
            raise ValueError("Unknown Studio canon/infill route")
        handler._form_json(200, result)
    except PermissionError as exc:
        handler._form_json(403, {"error": str(exc)})
    except (ValueError, KeyError, TypeError, sqlite3.Error, OSError) as exc:
        handler._form_json(400, {"error": str(exc)})


def run_canon_diff(timeline, req: dict) -> dict:
    """Compile story state at coord, run Pass 0-3 over draft/episode text, and optionally queue proposals."""
    episode = req.get("episode") or "spring-break"
    beat = int(req.get("beat", 0))
    viewpoint = req.get("viewpoint") or None
    source_origin = req.get("source_origin") or "author_manuscript"
    queue_proposals = bool(req.get("queue_proposals", False))
    with timeline._connect() as c:
        identity = verify_scope(c, project_id=req.get("project"), universe_id=req.get("universe"))
        ep = timeline.get_episode(episode) if req.get("episode") else None
        branch = req.get("branch") or (ep["branch"] if ep else "main")
        payload_input = (
            req.get("blocks")
            if "blocks" in req
            else (req.get("text") if "text" in req else (ep["script"] if ep else ""))
        )
        pos = resolve_episode_position(episode, req.get("episode_position"), c)
        coord = StoryCoord(identity["universe_id"], branch, episode, pos, beat)
        mem = sqlite3.connect(":memory:")
        mem.row_factory = sqlite3.Row
        try:
            mem.executescript(CANON_SCHEMA_SQL)
            if identity["kind"] == "afm-starters":
                seed_afm_universe(mem, universe_id=identity["universe_id"])
            _merge_conn_state(mem, c)
            report = run_canon_passes(payload_input, coord, mem, viewpoint=viewpoint, source_origin=source_origin)
            compiled = StateCompiler(mem).compile_state(coord, viewpoint=viewpoint)
        finally:
            mem.close()
        queued: list[str] = []
        if queue_proposals:
            c.execute("BEGIN IMMEDIATE")
            ensure_canon_schema(c)
            existing = {
                (p["episode_id"], p["kind"], p["payload"].get("op"), p["payload"].get("subject_id"), p["payload"].get("target_id"))
                for p in list_proposals(c, identity["universe_id"], status="pending")
            }
            for claim in report["claims"]:
                spec = claim.get("suggested_delta")
                if not spec:
                    continue
                sig = (coord.episode_id, spec["kind"], spec.get("op"), spec.get("subject_id"), spec.get("target_id"))
                if sig in existing:
                    continue
                queued.append(
                    propose_canon_change(
                        c,
                        coord,
                        kind=spec["kind"],
                        payload={
                            "op": spec["op"],
                            "subject_id": spec["subject_id"],
                            "target_id": spec.get("target_id"),
                            "payload": spec.get("payload", {}),
                        },
                        rationale=spec.get("rationale", "Extracted in Studio canon inspection"),
                    )
                )
                existing.add(sig)
        report["queued_proposals"] = queued
        report["relationships"] = {f"{a}->{b}": v for (a, b), v in compiled.relationships.items()}
        report["characters"] = compiled.characters
        plain_text = (
            "\n\n".join(str(b.get("text", "")) for b in payload_input)
            if isinstance(payload_input, list)
            else str(payload_input or "")
        )
        from prose_engine.canon_corrector import auto_correct_canon
        from prose_engine.voice.world_state import WorldState
        try:
            world_state = WorldState.load()
        except Exception:
            world_state = None
        corr = auto_correct_canon(
            plain_text,
            apply=True,
            compiled_state=compiled,
            world_state=world_state,
            episode_id=episode,
            branch=branch,
            beat=beat,
            viewpoint=viewpoint,
        )
        report["corrections"] = [c.to_dict() for c in corr.corrections]
        report["auto_corrected_text"] = corr.corrected_text
        report["remaining_after_auto_correct"] = list(corr.remaining_violations)
        if req.get("auto_correct"):
            report["corrected"] = bool(corr.applied_count)
        return report


def run_canon_proposals(timeline, req: dict) -> dict:
    """List, propose, resolve, or retire accumulative canon deltas/proposals in the workspace timeline DB."""
    action = req.get("action")
    with timeline._connect() as c:
        identity = verify_scope(c, project_id=req.get("project"), universe_id=req.get("universe"))
        c.execute("BEGIN IMMEDIATE")
        ensure_canon_schema(c)
        if action in ("open", "list"):
            episode = req.get("episode") or "spring-break"
            branch = req.get("branch") or "main"
            beat = int(req.get("beat", 0))
            compiled = compile_afm_state(
                universe_id=identity["universe_id"],
                branch=branch,
                episode_id=episode,
                episode_position=req.get("episode_position"),
                beat=beat,
                timeline_conn=c,
                seed_afm=(identity["kind"] == "afm-starters"),
            )
            return {
                "proposals": list_proposals(c, identity["universe_id"], status=req.get("status")),
                "state_digest": compiled.state_digest,
                "coord": compiled.coord.to_dict(),
                "relationships": {f"{a}->{b}": v for (a, b), v in compiled.relationships.items()},
            }
        if action == "propose":
            coord = StoryCoord(
                identity["universe_id"],
                req.get("branch") or "main",
                req["episode"],
                float(req.get("episode_position", 10.0)),
                int(req.get("beat", 0)),
            )
            pid = propose_canon_change(c, coord, kind=req["kind"], payload=req["payload"], rationale=req["rationale"])
            return {"proposal_id": pid, "status": "pending"}
        if action == "resolve":
            if identity["kind"] == "afm-starters" and not c.execute(
                "SELECT 1 FROM universe_laws_v2 WHERE universe_id=?", (identity["universe_id"],)
            ).fetchone():
                seed_afm_universe(c, universe_id=identity["universe_id"])
            return resolve_proposal(c, req["proposal_id"], req["decision"], req["reviewer"])
        if action == "retire_delta":
            if not retire_delta(c, req["delta_id"], retired=bool(req.get("retired", True))):
                raise ValueError("Unknown delta ID")
            return {"delta_id": req["delta_id"], "retired": bool(req.get("retired", True))}
        raise ValueError("Unknown canon proposal action")


def _opt_int(value, default: int) -> int:
    return default if value is None else int(value)


def _legacy_spring_for(timeline, episode: str, ep: dict, novel_path: Path | None) -> str | None:
    if ep.get("script") or episode != "spring-break":
        return None
    if timeline.scope().get("kind") != "afm-starters":
        return None
    candidate = novel_path if novel_path is not None else (Path(__file__).resolve().parents[1] / "work" / "americandad" / "foxy_mo2_hybrid_novel.md")
    return candidate.read_text(encoding="utf-8") if candidate.is_file() else None


def run_slot_infill(timeline, req: dict, *, novel_path: Path | None = None) -> dict:
    """Plan occurrence-safe 0/25/50/75/100% infill slots or validate/preview fills without mutating canon."""
    from prose_engine.notebook import NotebookStore
    from prose_engine.scoped_pipeline import build_infill_plan, build_packet, evaluate_infill_proposal

    action = req.get("action") or "plan"
    if action not in ("plan", "validate", "preview"):
        raise ValueError("Unknown slot infill action")

    use_standalone = "source_text" in req and not req.get("episode")
    if use_standalone:
        source_text = req["source_text"]
        ranges = req.get("protection_ranges") or ()
        default_tier = _opt_int(req.get("default_tier"), 0)
        plan = plan_infill_slots(source_text, ranges, default_tier=default_tier, base_offset=_opt_int(req.get("base_offset"), 0))
        if action == "plan":
            return {"action": "plan", "plan": plan.to_dict()}
        enforce = bool(req.get("enforce_tier_fidelity", True))
        allow_empty = bool(req.get("allow_empty", False))
        if "fills" in req:
            applied = apply_slot_fills(plan, req["fills"], validate=False, enforce_tier_fidelity=enforce, allow_empty=allow_empty)
            return {"action": action, **applied, "valid": applied["validation"]["valid"], "issues": applied["validation"]["issues"], "plan": plan.to_dict()}
        if "candidate_text" in req:
            se = tuple(req["source_edit"]) if req.get("source_edit") is not None else None
            report = validate_infill_seams(plan, req["candidate_text"], source_edit=se, enforce_tier_fidelity=enforce, allow_empty=allow_empty)
            return {"action": action, "valid": report.valid, "issues": report.issues, "text": req["candidate_text"], "validation": report.to_dict(), "plan": plan.to_dict()}
        raise ValueError("Slot infill validation requires fills or candidate_text")

    episode = req.get("episode") or "spring-break"
    ep = timeline.get_episode(episode)
    branch = req.get("branch") or ep["branch"]
    if branch != ep["branch"]:
        raise ValueError("Saved episode belongs to a different branch")
    revision = _opt_int(req.get("revision"), ep["head"])
    beat = _opt_int(req.get("beat"), 0)
    viewpoint = req.get("viewpoint") or None
    legacy_text = _legacy_spring_for(timeline, episode, ep, novel_path)
    script_text = ep["script"] or legacy_text or ""
    start = _opt_int(req.get("start"), 0)
    end = _opt_int(req.get("end"), len(script_text))
    nb = NotebookStore(timeline).existing(episode)
    req_ranges = req.get("protection_ranges")
    hard_only = [[r[0], r[1]] for r in req_ranges if r[2] == 100] if req_ranges else None
    packet = None
    try:
        packet = build_packet(
            timeline,
            episode,
            beat,
            revision,
            start,
            end,
            viewpoint=viewpoint,
            branch=branch,
            protected_ranges=hard_only,
            legacy_spring_text=legacy_text,
        )
    except ValueError as exc:
        if "unavailable at this beat" not in str(exc):
            raise
    default_tier = _opt_int(req.get("default_tier"), nb["default_protection"] if nb is not None else 0)
    if packet is not None:
        plan = (
            plan_infill_slots(packet.target, req_ranges, default_tier=default_tier, base_offset=packet.start)
            if req_ranges is not None
            else build_infill_plan(packet, default_tier=default_tier)
        )
    else:
        from prose_engine.notebook import resolve as resolve_nb_masks
        nb_ranges = (
            tuple((max(start, r["start"]), min(end, r["end"]), r["value"]) for r in resolve_nb_masks(script_text, nb["default_protection"], nb["masks"]) if r["start"] < end and start < r["end"])
            if nb is not None
            else ()
        )
        plan = plan_infill_slots(script_text[start:end], req_ranges if req_ranges is not None else nb_ranges, default_tier=default_tier, base_offset=start)
    if action == "plan":
        return {"action": "plan", "episode": episode, "branch": branch, "revision": revision, "plan": plan.to_dict()}
    enforce = bool(req.get("enforce_tier_fidelity", True))
    allow_empty = bool(req.get("allow_empty", False))
    if "fills" in req:
        if packet is not None:
            res = evaluate_infill_proposal(packet, req["fills"], plan=plan, default_tier=default_tier, enforce_tier_fidelity=enforce, allow_empty=allow_empty)
            return {"action": action, "episode": episode, "branch": branch, "revision": revision, **res}
        applied = apply_slot_fills(plan, req["fills"], validate=False, enforce_tier_fidelity=enforce, allow_empty=allow_empty)
        return {"action": action, "episode": episode, "branch": branch, "revision": revision, **applied, "valid": applied["validation"]["valid"], "issues": applied["validation"]["issues"], "plan": plan.to_dict()}
    if "candidate_text" in req:
        se = tuple(req["source_edit"]) if req.get("source_edit") is not None else None
        report = validate_infill_seams(plan, req["candidate_text"], source_edit=se, enforce_tier_fidelity=enforce, allow_empty=allow_empty)
        issues = list(report.issues)
        if packet is not None:
            from prose_engine.scoped_pipeline import validate_output
            for msg in validate_output(packet, req["candidate_text"], source_edit=se, check_seams=False, enforce_tier_fidelity=False):
                if msg not in issues:
                    issues.append(msg)
        return {
            "action": action,
            "episode": episode,
            "branch": branch,
            "revision": revision,
            "valid": len(issues) == 0,
            "issues": issues,
            "text": req["candidate_text"],
            "validation": report.to_dict(),
            "plan": plan.to_dict(),
        }
    raise ValueError("Slot infill validation requires fills or candidate_text")


def run_craft_brief(timeline, req: dict, *, novel_path: Path | None = None) -> dict:
    """Compile a <6 KB CraftBrief, critique prose via SlopCritic, or rank Best-of-N candidates."""
    from prose_engine.scoped_pipeline import build_packet
    from prose_engine.voice.slop_critic import SlopCritic
    from prose_engine.voice.synthesizer import (
        DeNovoSynthesizer,
        MAX_CRAFT_BRIEF_BYTES,
        extract_dialogue_skeleton,
    )

    action = req.get("action") or "compile"
    if action not in ("compile", "critique", "rank"):
        raise ValueError("Unknown craft brief action")

    critic = SlopCritic(
        use_saved_model=bool(req.get("use_saved_model", True)),
        require_burstiness=bool(req.get("require_burstiness", False)),
    )
    if action == "critique":
        return {"action": "critique", **critic.critique(req["text"]).to_dict()}

    packet = None
    source_text = str(req.get("source_text") or "")
    world_laws = list(req.get("world_laws") or [])
    if req.get("episode"):
        episode = req["episode"]
        ep = timeline.get_episode(episode)
        branch = req.get("branch") or ep["branch"]
        revision = _opt_int(req.get("revision"), ep["head"])
        legacy_text = _legacy_spring_for(timeline, episode, ep, novel_path)
        script_text = ep["script"] or legacy_text or ""
        start = _opt_int(req.get("start"), 0)
        end = _opt_int(req.get("end"), len(script_text))
        junctions = None
        form_path = getattr(timeline, "form_graph_path", None)
        if form_path is not None and Path(form_path).is_file():
            from story_graph.form_graph_store import FormGraphStore
            from story_graph.source_imports import junctions as imported_junctions
            with timeline._connect() as c:
                imp = imported_junctions(c, {})
            junctions = FormGraphStore(form_path, imported=imp).junctions()
        try:
            packet = build_packet(
                timeline,
                episode,
                _opt_int(req.get("beat"), 0),
                revision,
                start,
                end,
                viewpoint=req.get("viewpoint") or None,
                junctions=junctions,
                branch=branch,
                legacy_spring_text=legacy_text,
            )
            if not source_text:
                source_text = packet.target
            if not world_laws:
                world_laws = [law["statement"] for law in packet.world_laws]
        except ValueError as exc:
            if "unavailable at this beat" not in str(exc):
                raise
            if not source_text:
                source_text = script_text[start:end]
            if not world_laws:
                from story_graph.world_laws import WorldLawStore
                world_laws = [law["statement"] for law in WorldLawStore(timeline).open()["laws"]]

    scene_heading = str(req.get("scene_heading") or (packet.episode if packet else "SCENE"))
    beats = list(req.get("beats") or ([line.strip() for line in source_text.splitlines() if line.strip()][:6]))
    skeleton = extract_dialogue_skeleton(source_text) if source_text else ()
    max_bytes = _opt_int(req.get("max_bytes"), MAX_CRAFT_BRIEF_BYTES)
    synth = DeNovoSynthesizer(str(req.get("lens_id") or "irby"), critic=critic)

    mind_directives = list(req.get("mind_directives") or ())
    epistemic_withheld = list(req.get("epistemic_withheld") or ())
    craft_cues = list(req.get("craft_cues") or ())
    character_receipts = []
    book_status = {"state": "disabled", "count": 0}
    if packet is not None:
        character_receipts = packet.character_receipts()
        if not mind_directives:
            for cid, group in packet.characters.items():
                active = group.get("active_form") or cid
                bits = []
                for prof in group.get("profiles", ()):
                    for fld in prof.get("fields", ()):
                        if fld.get("category") in ("personality", "voice", "author_note", "behavior"):
                            txt = str(fld.get("text") or "").strip()
                            if txt:
                                prefix = "[uncertain] " if fld.get("confidence") == "uncertain" else ""
                                bits.append(f"{fld['category']}: {prefix}{txt[:120]}")
                if bits:
                    mind_directives.append(f"{cid} ({active}): " + "; ".join(bits[:2]))
        if not epistemic_withheld and packet.viewpoint:
            epistemic_withheld.append(
                f"Enforce POV {packet.viewpoint}: keep private/unrevealed forms and future beats unmentioned"
            )
        ref_backend = str(req.get("references") or "none")
        if ref_backend != "none" and not craft_cues:
            try:
                from prose_engine.scoped_references import DEFAULT_BOOKS, craft_observation, select_references
                bundle = select_references(
                    packet,
                    root=Path(req.get("books_dir")) if req.get("books_dir") else DEFAULT_BOOKS,
                    backend=ref_backend,
                    provider=str(req.get("provider") or "local"),
                    scene_function=str(req.get("scene_function") or "scene"),
                )
                obs = craft_observation(bundle["texts"])
                if obs:
                    craft_cues.append(
                        f"Reference cadence ({ref_backend}, {len(bundle['receipts'])} eligible): "
                        f"mean {obs['mean_sentence_words']}w, var {obs['sentence_length_variation']}, "
                        f"short clause {obs['short_clause_share']}"
                    )
                book_status = {
                    "state": "ready",
                    "backend": ref_backend,
                    "count": len(bundle["receipts"]),
                    "receipts": bundle["receipts"],
                }
            except Exception as exc:
                book_status = {"state": getattr(exc, "state", "unavailable"), "message": str(exc), "count": 0}

    if action == "compile":
        brief = synth.compile_brief(
            scene_heading,
            beats,
            skeleton,
            viewpoint=req.get("viewpoint") or (packet.viewpoint if packet else None),
            world_laws=world_laws,
            mind_directives=mind_directives,
            epistemic_withheld=epistemic_withheld,
            craft_cues=craft_cues,
            max_bytes=max_bytes,
            seed=req.get("seed"),
        )
        return {
            "action": "compile",
            "brief": brief.to_dict(),
            "skeleton_count": len(skeleton),
            "character_receipts": character_receipts,
            "character_count": len(packet.characters) if packet is not None else 0,
            "book_status": book_status,
        }

    raw_candidates = list(req.get("candidates") or [])
    if not raw_candidates:
        raise ValueError("Craft brief ranking requires a non-empty candidates list")
    queue = list(raw_candidates)
    res = synth.synthesize_best_of_n(
        lambda _prompt: queue.pop(0),
        scene_heading,
        beats,
        skeleton,
        n=len(raw_candidates),
        reference_text=source_text,
        margin=float(req.get("margin", 0.03)),
        require_order=bool(req.get("require_order", True)),
        viewpoint=req.get("viewpoint") or (packet.viewpoint if packet else None),
        world_laws=world_laws,
        mind_directives=mind_directives,
        epistemic_withheld=epistemic_withheld,
        craft_cues=craft_cues,
        max_bytes=max_bytes,
        packet=packet,
    )
    return {"action": "rank", "character_receipts": character_receipts, "book_status": book_status, **res}
