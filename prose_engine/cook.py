"""Revision-bound preparation of saved Noir text. No provider or canon writes."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from typing import Callable

from story_graph.director import fingerprint
from story_graph.form_graph_store import FormGraphStore, register_cue
from story_graph.scene_fragments import SceneFragmentStore
from story_graph.universe_scope import verify_scope
from .notebook import NotebookStore, digest
from .scene_bridges import scoped_form_store

_HEADING = re.compile(
    r"^(?:#{1,6}\s+|(?:\*{1,2})?(?:INT\.|EXT\.|INT/EXT\.|I/E\.|"
    r"(?:SCENE|SECTION|CHAPTER)\s+\d+\b|PROLOGUE\b|EPILOGUE\b))",
    re.IGNORECASE,
)
_DIRECTION = re.compile(
    r"^(?:\([^)\r\n]+\)$|\[?(?:stage(?: direction| notes?)?|action|sfx|camera|beat|production note|missing detail)\]?\s*:|"
    r"(?:cut to|smash cut to|fade in|fade out|dissolve to)\s*[:.]?$)", re.IGNORECASE,
)
_NARRATION = re.compile(
    r"^(?:\*\*)?\[?(?:narrator|narration|world(?: description)?|setting|location|time|notes?|summary|title|synopsis)\]?(?:\*\*)?\s*:",
    re.IGNORECASE,
)
_DOCUMENT_NOTE = re.compile(r"^(?:===|<!--|(?:chunk|page)\s+\d+\b)|\bS\d{1,2}E\d{1,3}\s*:", re.IGNORECASE)
_NAME = r"([^\W\d_][\w .’'\-]{0,44}?)"
_CUE = re.compile(r"^(?:\*\*)?@?" + _NAME + r"(?:[ \t]*\([^)]*\))*(?:[ \t]*(?:\*\*)?:|[ \t]+[-—][ \t]+)(?:\*\*)?")
_CUE_LINE = re.compile(r"^(?:\*\*)?@?" + _NAME + r"(?:[ \t]*\([^)]*\))*[ \t]*(?:\*\*)?$")
_PAREN_CUE = re.compile(r"^(?:\*\*)?@?" + _NAME + r"(?:[ \t]*\([^)]*\))+[ \t]+(?=\S)")
_RESERVED_CUES = frozenset({"end", "the_end", "narrator", "narration", "stage_direction",
                            "world_description", "setting", "summary", "transition"})
_PAREN_TAG_RE = re.compile(r"\(([^()\r\n]{1,48})\)")
_ALIASES = {
    "hayley": "haley",
    "holly_graham": "holly",
    "chief": "chief_scientist",
    "mama_ling": "ma_ma_ling",
    "ma_ma": "ma_ma_ling",
    "rainee_peter_griffen": "peter_griffin_celestial_variant",
    "rainee_peter_griffin": "peter_griffin_celestial_variant",
    "rainee_peter": "peter_griffin_celestial_variant",
    "peter_rainee": "peter_griffin_celestial_variant",
    "nurse_franny": "nurse_pamela_franny_anderson",
    "nurse_frann_anderson": "nurse_pamela_franny_anderson",
    "nurse_pamela_anderson": "nurse_pamela_franny_anderson",
    "big_tiddy_steve": "big_tiddy_steve_stella",
    "big_tiddy_nerdy_female_boy_stella": "big_tiddy_steve_stella",
    "big_tiddy_nerdy_female_boy_stell": "big_tiddy_steve_stella",
    "big_tiddy_nerdy": "big_tiddy_steve_stella",
    "big_tiddy_nerd": "big_tiddy_steve_stella",
    "steve": "big_tiddy_steve_stella",
    "hayley_fitness_goddess": "awakened_haley_fox",
    "haley_fitness_goddess": "awakened_haley_fox",
    "fitness_goddess": "awakened_haley_fox",
    "awakened_fox": "awakened_haley_fox",
    "rainee_1": "rainee-split-1",
    "rainee_sade": "rainee-split-1",
    "sade": "rainee-split-1",
    "rainee_1_sade": "rainee-split-1",
    "rainee_1_rainee_sade": "rainee-split-1",
    "rainee_2": "rainee-split-2",
    "rainee_becky": "rainee-split-2",
    "becky": "rainee-split-2",
    "rainee_2_becky": "rainee-split-2",
    "rainee_2_rainee_becky": "rainee-split-2",
    "rainee_3": "rainee-split-3",
    "rainee_clarie": "rainee-split-3",
    "clarie": "rainee-split-3",
    "rainee_claire": "rainee-split-3",
    "claire": "rainee-split-3",
    "rainee_3_clarie": "rainee-split-3",
    "rainee_3_rainee_clarie": "rainee-split-3",
}


def _key(value):
    return re.sub(r"[\W_]+", "_", unicodedata.normalize("NFKC", value or "").casefold()).strip("_")


def _speaker_index(junctions):
    candidates = defaultdict(set)
    for junction in junctions:
        cid, forms = junction["character_id"], junction["forms"]
        base = next((form for form in forms if form.get("kind") == "base"), forms[0])
        for name in (cid, junction.get("label")):
            if key := _key(name):
                candidates[key].add((cid, base["id"]))
        for form in forms:
            for name in (form["id"], form.get("label"), form.get("display_label")):
                if key := _key(name):
                    candidates[key].add((cid, form["id"]))
    for alias, name in _ALIASES.items():
        if name in candidates:
            candidates[alias].update(candidates[name])
        elif alt_key := _key(name):
            candidates[alias].update(candidates.get(alt_key, ()))
    return candidates


def _looks_like_name(label):
    words = re.findall(r"[^\W_]+", label)
    return (0 < len(words) <= 5 and words[0][0].isupper() and
            all(word[0].isupper() or word.isdecimal() or word in {'de', 'da', 'van', 'von'} for word in words))


def _classify(line, candidates, has_followup, starts_paragraph):
    if _HEADING.match(line):
        return "scene-heading", None, None, None, None
    if _DIRECTION.match(line):
        return "stage-direction", None, None, None, None
    if _NARRATION.match(line) or _DOCUMENT_NOTE.search(line):
        return "narrator", None, None, None, None
    formatted = line.removeprefix("**").startswith("@")
    match = _CUE.match(line) or _PAREN_CUE.match(line)
    standalone = False
    if match is None and has_followup:
        match = _CUE_LINE.fullmatch(line)
        standalone = True
    if match:
        label = match[1].strip()
        key = _key(label)
        choices = candidates.get(key, ())
        prefix = line[:match.end()].rstrip()
        if standalone:
            looks_like_cue = formatted or (label.isupper() and (choices or starts_paragraph))
        else:
            name = _looks_like_name(label) and (not prefix.endswith(("—", "-")) or " " in label)
            looks_like_cue = formatted or bool(choices) or label.isupper() or name
        if key not in _RESERVED_CUES and looks_like_cue:
            if len(choices) == 1:
                cid, form_id = next(iter(choices))
                for paren in _PAREN_TAG_RE.findall(prefix):
                    if pchoices := candidates.get(_key(paren)):
                        same_char = [pair for pair in pchoices if pair[0] == cid]
                        if len(same_char) == 1:
                            cid, form_id = same_char[0]
                            break
                return "character", cid, form_id, label, prefix
            return "unresolved", None, None, label, prefix
    return "narrator", None, None, None, None


def _range_blocks(block, candidates, *, initial_import=False):
    """Classify source ranges while keeping all original characters and separators."""
    text = block["text"]
    kind = block["kind"]
    if (kind != "unresolved" and not (initial_import and kind == "narrator")
            or block.get("binding_evidence") or not text.strip()):
        return [dict(block)]
    source = block.get("source")
    if (kind == "unresolved" and block.get("cue_label") and isinstance(source, dict)
            and source.get("sha256") == digest(text)):
        # Intake already parsed the complete cue, including any dialogue split by a stage note.
        return [dict(block)]
    parts = text.splitlines(keepends=True)
    runs = []
    cursor = 0
    dialogue = None
    for index, raw in enumerate(parts):
        start, cursor = cursor, cursor + len(raw)
        line = raw.strip()
        if not line:
            if runs:
                runs[-1][1] = cursor
            dialogue = None
            continue
        following = parts[index + 1].strip() if index + 1 < len(parts) else ""
        has_followup = bool(following and not _HEADING.match(following))
        boundary = index == 0 or not parts[index - 1].strip() or following.startswith("(")
        label = _classify(line, candidates, has_followup, boundary)
        continuation = (label[0] == "narrator" and dialogue is not None
                        and not _NARRATION.match(line) and not _DOCUMENT_NOTE.search(line))
        if continuation:
            if runs and runs[-1][2][:4] == dialogue[:4]:
                runs[-1][1] = cursor
                continue
            label = dialogue
        elif label[3]:
            dialogue = (*label[:4], None)
        elif not (label[0] == "stage-direction" and line.startswith("(")):
            dialogue = None
        if label[0] == "narrator" and runs and runs[-1][2] == label:
            runs[-1][1] = cursor
        else:
            runs.append([start if runs else 0, cursor, label])
    if not runs:
        return [dict(block)]
    anchored = (isinstance(source, dict) and type(source.get("start")) is int and source["start"] >= 0
                and source.get("end") == source["start"] + len(text) and source.get("sha256") == digest(text))
    result = []
    for index, (start, end, (kind, speaker, form, label, prefix)) in enumerate(runs):
        segment = text[start:end]
        entry = dict(block, kind=kind, speaker=speaker, form=form, text=segment)
        entry.pop("cue_label", None)
        entry.pop("cue_prefix", None)
        if label is not None:
            entry["cue_label"] = label
        if prefix and segment.startswith(prefix) and len(prefix) <= 128:
            entry["cue_prefix"] = prefix
        if index:
            entry["id"] = hashlib.sha256(f"{block['id']}\0{start}\0{end}".encode()).hexdigest()[:32]
        if len(runs) > 1:
            if anchored:
                entry["source"] = dict(source, start=source["start"] + start,
                                       end=source["start"] + end, sha256=digest(segment))
            else:
                entry.pop("source", None)
        result.append(entry)
    return result


def classify_saved_blocks(blocks, junctions, *, initial_import=False):
    """Share source-exact classification between the first import and later Cook."""
    candidates = _speaker_index(junctions)
    return [part for block in blocks for part in _range_blocks(block, candidates, initial_import=initial_import)]


def _bind_cues(connection, scope, blocks, junctions, revision):
    candidates = _speaker_index(junctions)
    added = 0
    offset = 0
    for block in blocks:
        end = offset + len(block["text"])
        label = block.get("cue_label")
        if block["kind"] == "unresolved" and label and not block.get("binding_evidence"):
            raw_key = _key(label)
            key = _ALIASES.get(raw_key, raw_key)
            choices = candidates.get(raw_key) or candidates.get(key)
            if not choices:
                group = register_cue(connection, scope, key, label,
                                     {"timeline_revision":revision, "start":offset, "end":end,
                                      "sha256":digest(block["text"])})
                junctions.append(group.project(planning=True))
                choices = {(group.character_id, group.forms[0].id)}
                candidates[key] = set(choices)
                candidates[raw_key] = set(choices)
                for alias, target in _ALIASES.items():
                    if _key(target) == key or target == key:
                        candidates[alias].update(choices)
                added += 1
            if len(choices) == 1:
                speaker, form = next(iter(choices))
                block.update(kind="character", speaker=speaker, form=form)
        offset = end
    return added


def _used_sockets(blocks, junctions, planned_forms=()):
    forms = {group["character_id"]: {form["id"]: form for form in group["forms"]} for group in junctions}
    used = {}
    cues = [(block.get("speaker"), block.get("form")) for block in blocks if block.get("speaker")]
    cues.extend((item["character"], item["form"]) for item in planned_forms)
    for character, form_id in cues:
        group = forms.get(character)
        if not group:
            continue
        form_id = form_id or next(iter(group))
        if form := group.get(form_id):
            used[form["port_id"]] = {"character":character, "junction":f"character:{character}",
                                     "form":form_id, "port":form["port_id"], "mind":form.get("link")}
    return list(used.values())


def _save_preparation(connection, payload):
    connection.execute("""CREATE TABLE IF NOT EXISTS episode_preparations(
        id TEXT PRIMARY KEY, episode TEXT NOT NULL REFERENCES episodes(id), timeline_revision INTEGER NOT NULL,
        notebook_revision INTEGER NOT NULL, payload TEXT NOT NULL)""")
    ident = fingerprint(payload)
    receipt = {"id":ident, **payload}
    inserted = connection.execute("INSERT OR IGNORE INTO episode_preparations VALUES(?,?,?,?,?)", (
        ident, payload["episode"], payload["timeline_revision"], payload["notebook_revision"],
        json.dumps(receipt, ensure_ascii=False),
    )).rowcount
    return receipt, not inserted


def current_preparation(connection, episode, revision):
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='episode_preparations'"
    ).fetchone():
        return None
    row = connection.execute("""SELECT p.payload FROM episode_preparations p
        JOIN notebook_heads h ON h.episode=p.episode AND p.notebook_revision=h.head
        WHERE p.episode=? AND p.timeline_revision=? ORDER BY p.rowid DESC LIMIT 1""", (episode, revision)).fetchone()
    return json.loads(row[0]) if row else None


def render_context(timeline, connection, packet, preparation, books_root):
    """Bind the writer to the current saved preparation and exact scoped references."""
    from pathlib import Path
    from story_graph.beat_rhythm import read_act_structure
    from story_graph.world_laws import check_laws
    from . import media_graph
    from .conditioner import build_rhythm_skeleton
    from .scoped_references import DEFAULT_BOOKS

    prepared = current_preparation(connection, packet.episode, packet.revision)
    if not prepared or prepared['id'] != preparation or prepared['scope_revision'] != packet.context.scope_revision:
        raise ValueError('Prepare the saved episode again before rendering this passage.')
    scope = {key: prepared[key] for key in ('project', 'universe', 'scope_revision', 'episode', 'branch')}
    overlap = lambda start, end: start < packet.end and packet.start < end

    def safe_direction(text):
        return (not check_laws(text, packet.world_laws)
                and not any(hidden.casefold() in text.casefold() for hidden in packet.hidden_phrases))

    def relevant(target):
        if target.get('timeline_revision') != packet.revision or target.get('source_sha256') != prepared['source_sha256']:
            return False
        if target['kind'] == 'beat':
            passage = target['passage']
            return overlap(passage['start'], passage['end'])
        return any(target['scene'] in (fragment['scene'], fragment['id'])
                   and overlap(fragment['anchor']['start'], fragment['anchor']['end'])
                   for fragment in prepared['fragments'])

    pins = [pin for pin in media_graph._pins(connection, media_graph._pin_scope(scope))
            if relevant(pin['target'])]
    active = []
    for character, group in packet.forms.items():
        for form in group['forms']:
            if form['status'] != 'active':
                continue
            active.append({'character': character, 'form': form['id'], 'link': form.get('link')})
            port = {'kind': 'form', 'port': form['port_id']}
            pins.extend(media_graph._pins(connection, media_graph._pin_scope(scope, port)))
    references = []
    for pin in sorted(pins, key=lambda item: item['id'])[:24]:
        linked = media_graph._link(connection, scope, pin)
        if linked:
            asset, segment = linked['asset'], linked['segment']
            media_graph.original_in_scope(timeline, connection, scope, asset['id'])
            note = segment['observation']
            if safe_direction(note):
                references.append({'pin': pin['id'], 'asset_sha256': asset['sha256'], 'kind': asset['kind'],
                                   'role': segment.get('pin_role') or segment['purpose'],
                                   'selector': segment['selector'], 'observation': note})
    structure = read_act_structure(timeline, connection, packet.episode, packet.revision)
    timing = []
    for point in structure['points']:
        if not overlap(point['start'], point['end']):
            continue
        row = {key: point[key] for key in ('id', 'act', 'marker', 'tension', 'duration_ms', 'pace', 'direction', 'sight', 'audio')}
        for key in ('marker', 'direction'):
            if not safe_direction(row[key]):
                row[key] = ''
        timing.append(row)
    books = Path(books_root or DEFAULT_BOOKS)
    manifest = books / 'manifest.json'
    library_stamp = hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.is_file() else 'unavailable'
    skeleton = build_rhythm_skeleton({'target_burstiness': 4.0}, books_dir=books)
    return {'preparation': preparation, 'forms': active, 'pins': references, 'timing': timing[:24],
            'preset': structure['preset'], 'timing_revision': structure['revision'],
            'canon_tag': timeline._canon_tag(connection, packet.episode, packet.revision),
            'library_manifest_sha256': library_stamp, 'skeleton': skeleton}


def guard_render_context(timeline, connection, packet):
    if packet.compositor and render_context(timeline, connection, packet, packet.compositor['preparation'],
                                            packet.compositor_books) != packet.compositor:
        raise ValueError('Cook inputs changed; render again from the current saved context.')


def prepare_episode(timeline, request, *, form_store=None, progress_cb=None):
    return run_cook_pipeline(timeline, form_store or FormGraphStore(timeline.form_graph_path), request["episode"],
                             viewpoint=request.get("viewpoint"), expected_timeline_revision=request.get("timeline_revision"),
                             expected_notebook_revision=request.get("notebook_revision"), branch=request.get("branch"),
                             project=request.get("project"), universe=request.get("universe"), progress_cb=progress_cb)


def run_cook_pipeline(
    timeline,
    form_store,
    episode_id: str,
    *,
    viewpoint: str | None = None,
    expected_timeline_revision: int | None = None,
    expected_notebook_revision: int | None = None,
    branch: str | None = None,
    project: str | None = None,
    universe: str | None = None,
    progress_cb: Callable[[int, int, str, str], None] | None = None,
) -> dict:
    """Commit typed blocks, cue sockets and scene DAGs together."""
    def emit(stage, progress, state, message):
        if progress_cb is not None:
            progress_cb(stage, progress, state, message)

    revision = expected_timeline_revision
    if revision is None:
        revision = timeline.get_episode(episode_id)["head"]
    emit(1, 15, "running", "Reading exact saved text and protection settings.")
    junctions = []
    scope = {}
    created = 0
    universe_kind = ""

    def type_blocks(connection, state, notebook_revision):
        nonlocal created, universe_kind
        identity = verify_scope(connection, project_id=project, universe_id=universe)
        if branch is not None and state["branch"] != branch:
            raise ValueError("The saved episode belongs to a different branch")
        universe_kind = identity["kind"]
        scope.update(project=identity["project_id"], universe=identity["universe_id"],
                     scope_revision=identity["scope_revision"], episode=episode_id, branch=state["branch"])
        junctions.extend(scoped_form_store(connection, form_store, episode_id).read()["junctions"])
        initial_import = notebook_revision == 0 and connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='episode_intake'"
        ).fetchone() and connection.execute(
            "SELECT 1 FROM episode_intake WHERE episode=? AND original IS NOT NULL", (episode_id,)
        ).fetchone()
        blocks = classify_saved_blocks(state["blocks"], junctions, initial_import=bool(initial_import))
        emit(1, 35, "done", f"Typed {len(blocks)} blocks from the saved revision.")
        emit(2, 50, "running", "Resolving speaker cues and character sockets.")
        created = _bind_cues(connection, scope, blocks, junctions, revision)
        return blocks

    def publish(connection, state, mapping):
        from .scene_plan import preparation_sockets
        replay = preparation_sockets(connection, scope)
        sockets = _used_sockets(state["blocks"], junctions, replay["forms"] if replay else ())
        emit(2, 75, "done", f"{len(sockets)} forms used · {created} empty character junctions added.")
        emit(3, 85, "running", "Saving scene graphs and beat order.")
        fragments = SceneFragmentStore(timeline).prepare_scenes(connection, scope, mapping)
        canon_audit = None
        has_canon = any(
            connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
            for t in ("universe_laws_v2", "state_deltas")
        )
        if universe_kind == "afm-starters" or has_canon:
            import sqlite3
            from story_graph.canon_models import StoryCoord
            from story_graph.seeds.afm_seed import seed_afm_universe
            from story_graph.state_compiler import CANON_SCHEMA_SQL
            from .canon_guard import _merge_conn_state, resolve_episode_position
            from .fact_extractor import run_canon_passes

            pos = resolve_episode_position(episode_id, timeline_conn=connection)
            coord = StoryCoord(scope["universe"], state["branch"], episode_id, pos, 0)
            mem = sqlite3.connect(":memory:")
            mem.row_factory = sqlite3.Row
            try:
                mem.executescript(CANON_SCHEMA_SQL)
                if universe_kind == "afm-starters":
                    seed_afm_universe(mem, universe_id=scope["universe"])
                _merge_conn_state(mem, connection)
                report = run_canon_passes(state["blocks"], coord, mem, viewpoint=viewpoint)
                canon_audit = {
                    "state_digest": report["state_digest"],
                    "conflicts": len(report["conflicts"]),
                    "warnings": len(report["warnings"]),
                    "advisories": len(report["advisories"]),
                }
            finally:
                mem.close()
        return _save_preparation(connection, {
            "schema_version":1, **scope, "timeline_revision":revision, "notebook_revision":state["revision"],
            "source_sha256":mapping["source_sha256"], "fragments":fragments, "sockets":sockets,
            **({"turn_sockets": replay} if replay else {}),
            **({"canon_audit": canon_audit} if canon_audit is not None else {}),
            "passages":[beat["id"] for beat in mapping["beats"]], "provider_calls":0,
        })

    notebook = NotebookStore(timeline)
    result, mapping, before, (receipt, reused) = notebook.prepare_structure(
        episode_id, revision, type_blocks, publish, viewpoint=viewpoint, expected=expected_notebook_revision,
    )
    blocks = result["blocks"]
    linked = sum(block["kind"] == "character" and bool(block.get("speaker")) for block in blocks)
    unassigned = sum(block["kind"] == "unresolved" for block in blocks)
    emit(3, 100, "done", f"{len(receipt['fragments'])} scene graphs saved · {len(mapping['beats'])} mapped beats.")
    return {
        "episode": episode_id, "revision": result["revision"], "timeline_revision": revision,
        "stage1": {"blocks_before": before, "blocks_after": len(blocks), "split_applied": before != len(blocks)},
        "stage2": {"characters_added": created, "linked_character_blocks": linked,
                   "unresolved_blocks": unassigned, "total_junctions": len(junctions)},
        "stage3": {"scenes": len(mapping["scenes"]), "beats": len(mapping["beats"]),
                   "words": sum(len(block["text"].split()) for block in blocks), "revision": result["revision"]},
        "receipt":receipt, "reused":reused, "provider_calls":0,
    }
