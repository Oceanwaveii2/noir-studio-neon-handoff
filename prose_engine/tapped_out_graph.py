"""Smart Prose-Engine character & transformation graph synthesizer for Tapped Out and script rewrites."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_graph.form_graph_store import FormGraphStore
from .cook import _ALIASES, _PAREN_TAG_RE, _key, classify_saved_blocks, run_cook_pipeline

KNOWN_CHARACTER_ROSTER = {
    "holly": {
        "label": "Holly",
        "mind_label": "Holly Graham",
        "aliases": ("holly", "holly_graham"),
        "rank": "ruler",
        "visual_anchors": ("blonde", "studio"),
        "behavior": "Hollywood/studio authority introduced in Tapped Out; composes cleanly beside the Ling household cast.",
    },
}

KNOWN_TRANSFORMATION_SPECS = (
    {
        "character_id": "stella",
        "form_id": "big_tiddy_steve_stella",
        "label": "Big Tiddy Steve Stella",
        "kind": "transformation",
        "after": "stella",
        "patterns": (
            re.compile(r"\b(?:big\s+tiddy\s+(?:steve|nerdy?|female\s+boy\s+stell[a]?)|rocket[- ]?ship\s+underwear)\b", re.IGNORECASE),
            re.compile(r"\bStella\b[^.\n]{0,80}\b(?:transforms?|turns?|shifts?|morphs?|becomes?)\b[^.\n]{0,50}\b(?:Big\s+Tiddy\s+Steve|Steve)\b", re.IGNORECASE),
        ),
    },
    {
        "character_id": "stella",
        "form_id": "stella.state.nerd_20",
        "label": "Dork transformation 20%",
        "kind": "stage",
        "after": "stella",
        "patterns": (
            re.compile(r"\b(?:slips?\s+into\s+(?:a\s+)?(?:canary[- ]yellow\s+)?polo|buttons?\s+(?:pop|burst|snap))\b", re.IGNORECASE),
        ),
    },
    {
        "character_id": "stella",
        "form_id": "stella.state.nerd_80",
        "label": "Dork transformation 80%",
        "kind": "stage",
        "after": "stella.state.nerd_20",
        "patterns": (
            re.compile(r"\b(?:dork\s+transformation\s+80%)\b", re.IGNORECASE),
        ),
    },
    {
        "character_id": "francine",
        "form_id": "nurse_pamela_franny_anderson",
        "label": "Nurse Frann Anderson",
        "kind": "transformation",
        "after": "francine",
        "patterns": (
            re.compile(r"\bNurse\s+(?:Pamela\s+)?Frann?(?:y|ie)?(?:\s+Anderson)?\b", re.IGNORECASE),
        ),
    },
    {
        "character_id": "haley",
        "form_id": "awakened_haley_fox",
        "label": "Big Booty Haley — Awakened Fox",
        "kind": "transformation",
        "after": "haley",
        "patterns": (
            re.compile(r"\b(?:Awakened\s+Fox|Hayley\s+Fitness\s+Goddess|Haley\s+Fitness\s+Goddess)\b", re.IGNORECASE),
        ),
    },
)

_HOLLY_PROSE_RE = re.compile(r"\bHolly(?:\s+Graham)?\b")
_PAREN_TRANSFORM_CUE_RE = re.compile(
    r"^\s*(?:\*\*)?@?([A-Za-z][A-Za-z .'\-]{1,36}?)\s*\(([^()\r\n]{2,48})\)\s*(?:\*\*)?:",
    re.MULTILINE,
)
_EXPLICIT_TRANSFORM_LINE_RE = re.compile(
    r"\b([A-Z][a-z]+)\b[^.\n]{0,60}\b(?:transforms?\s+into|becomes?|shifts?\s+into|morphs?\s+into)\s+"
    r"(?:the\s+|her\s+|his\s+)?([A-Z][A-Za-z0-9'\-]*(?:\s+[A-Z0-9][A-Za-z0-9'\-]*){0,5})(?=[.,!?\n]|\s+(?:in|with|at|on|under|while|after|before)\b|$)"
)
_STAGE_MODIFIERS = frozenset({"quietly", "softly", "loudly", "aside", "angry", "smiling", "o_s", "os", "v_o", "vo", "cont_d", "contd", "pause", "whispering", "laughing"})


def _index_existing_junctions(payload: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[Tuple[str, str], str], Dict[str, Dict[str, Any]]]:
    """Build case-insensitive lookups for existing character junctions and their form ports."""
    by_cid = {g["character_id"]: g for g in payload.get("junctions", ())}
    char_lookup: Dict[str, str] = {}
    form_lookup: Dict[Tuple[str, str], str] = {}

    for cid, group in by_cid.items():
        char_lookup[_key(cid)] = cid
        if label := group.get("label"):
            char_lookup[_key(label)] = cid
        for form in group.get("forms", ()):
            fid = form["id"]
            if form.get("kind") == "base":
                char_lookup[_key(fid)] = cid
                char_lookup[_key(form.get("label", ""))] = cid
            for name in (fid, form.get("label"), form.get("display_label")):
                if k := _key(name):
                    form_lookup[(cid, k)] = fid
    # Register canonical character aliases into char_lookup if that character already exists.
    for roster_id, spec in KNOWN_CHARACTER_ROSTER.items():
        if roster_id in by_cid:
            for alias in spec["aliases"]:
                char_lookup[alias] = roster_id
    for cid in by_cid:
        if cid == "haley":
            char_lookup["hayley"] = "haley"
    return char_lookup, form_lookup, by_cid


def synthesize_character_graph_for_script(
    script_text: str,
    *,
    form_store: FormGraphStore,
    roster_profiles: Optional[Dict[str, Dict[str, Any]]] = None,
    link_new_character_minds: bool = True,
) -> Dict[str, Any]:
    """Inspect rewritten prose/cues, reuse existing characters/forms, attach transformations, and add new ones."""
    payload = form_store.read()
    revision = payload["revision"]
    roster = {**KNOWN_CHARACTER_ROSTER, **(roster_profiles or {})}

    char_lookup, form_lookup, by_cid = _index_existing_junctions(payload)
    reused_characters: List[str] = []
    added_characters: List[Dict[str, str]] = []
    reused_forms: List[Dict[str, str]] = []
    added_forms: List[Dict[str, str]] = []
    merged_legacy_cues: List[Dict[str, str]] = []
    transitions: List[Dict[str, Any]] = []

    def mark_reused_char(cid: str) -> None:
        if cid not in reused_characters and cid not in {a["character_id"] for a in added_characters}:
            reused_characters.append(cid)

    def mark_reused_form(cid: str, fid: str) -> None:
        pair = {"character_id": cid, "form_id": fid}
        if pair not in reused_forms and pair not in added_forms:
            reused_forms.append(pair)

    def ensure_character(raw_key: str, display_label: str) -> str:
        nonlocal payload, revision, char_lookup, form_lookup, by_cid
        canonical_key = _ALIASES.get(raw_key, raw_key)
        existing_cid = char_lookup.get(raw_key) or char_lookup.get(canonical_key)
        if existing_cid:
            mark_reused_char(existing_cid)
            if raw_key != _key(existing_cid) and display_label:
                merged_legacy_cues.append({"cue": display_label, "resolved_to": existing_cid})
            return existing_cid

        spec = roster.get(canonical_key)
        label = spec["label"] if spec else display_label.strip()
        req: Dict[str, Any] = {"action": "add_character", "revision": revision, "label": label}
        if spec or re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", canonical_key):
            req["character_id"] = canonical_key
        payload = form_store.change(req)
        revision = payload["revision"]
        char_lookup, form_lookup, by_cid = _index_existing_junctions(payload)
        created_cid = next(
            (g["character_id"] for g in payload["junctions"] if g["forms"][0]["label"].casefold() == label.casefold()),
            req.get("character_id", ""),
        )
        added_characters.append({"character_id": created_cid, "label": label})

        if link_new_character_minds and created_cid:
            group = by_cid[created_cid]
            base_port = group["forms"][0]["port_id"]
            if spec and not group["forms"][0].get("link"):
                payload = form_store.change({
                    "action": "create_mind_link",
                    "revision": revision,
                    "port": base_port,
                    "label": spec.get("mind_label") or label,
                    "kind": "digital_mind",
                })
                revision = payload["revision"]
                payload = form_store.change({
                    "action": "save_node_data",
                    "revision": revision,
                    "character": created_cid,
                    "node": "data:" + base_port,
                    "content": {
                        "text_fields": {"behavior": spec.get("behavior", f"Character introduced in rewrite: {label}.")},
                        "structured_data": {
                            "rank": spec.get("rank", "supporting"),
                            "visual_anchors": list(spec.get("visual_anchors", ())),
                            "aliases": list(spec.get("aliases", (canonical_key,))),
                        },
                    },
                })
                revision = payload["revision"]
                char_lookup, form_lookup, by_cid = _index_existing_junctions(payload)
        return created_cid

    def ensure_form(cid: str, form_id: str, label: str, kind: str = "transformation", after: Optional[str] = None) -> str:
        nonlocal payload, revision, char_lookup, form_lookup, by_cid
        group = by_cid.get(cid)
        if not group:
            return form_id
        fk = _key(form_id)
        lk = _key(label)
        existing = form_lookup.get((cid, fk)) or form_lookup.get((cid, lk))
        if existing:
            mark_reused_form(cid, existing)
            return existing
        base_id = group["forms"][0]["id"]
        parent_id = after if (after and any(f["id"] == after for f in group["forms"])) else base_id
        if kind not in {"persona", "transformation", "stage"}:
            kind = "transformation"
        payload = form_store.change({
            "action": "add_form",
            "revision": revision,
            "character": cid,
            "form_id": form_id,
            "label": label,
            "kind": kind,
            "after": parent_id,
        })
        revision = payload["revision"]
        char_lookup, form_lookup, by_cid = _index_existing_junctions(payload)
        added_forms.append({"character_id": cid, "form_id": form_id, "label": label, "kind": kind, "after": parent_id})
        return form_id

    # 1. Classify script cues against current junctions first.
    junctions = payload.get("junctions", ())
    raw_blocks = [{"id": "script-0", "kind": "narrator", "speaker": None, "form": None, "text": script_text}]
    blocks = classify_saved_blocks(raw_blocks, junctions, initial_import=True)

    for b in blocks:
        kind = b.get("kind")
        if kind == "character" and b.get("speaker"):
            cid = b["speaker"]
            mark_reused_char(cid)
            if fid := b.get("form"):
                mark_reused_form(cid, fid)
            cue_label = b.get("cue_label") or ""
            if cue_label and _key(cue_label) not in {_key(cid), _key(fid or "")}:
                merged_legacy_cues.append({"cue": cue_label, "resolved_to": f"{cid}:{fid}"})
        elif kind == "unresolved" and b.get("cue_label"):
            label = b["cue_label"].strip()
            raw_k = _key(label)
            alias_target = _ALIASES.get(raw_k)
            # Check if the unresolved cue is actually a known form or truncated form of an existing character!
            matched_pair = None
            if alias_target:
                for (cid_k, fk), fid_v in form_lookup.items():
                    if fk == _key(alias_target) or fid_v == alias_target:
                        matched_pair = (cid_k, fid_v)
                        break
            if matched_pair:
                cid, fid = matched_pair
                mark_reused_char(cid)
                mark_reused_form(cid, fid)
                merged_legacy_cues.append({"cue": label, "resolved_to": f"{cid}:{fid}"})
            else:
                ensure_character(raw_k, label)

    # 2. Scan parenthetical transformation cues like `STELLA (Big Tiddy Steve):` or `Stella (Turbo Nerd):`
    for char_name, tag in _PAREN_TRANSFORM_CUE_RE.findall(script_text):
        tk = _key(tag)
        if not tk or tk in _STAGE_MODIFIERS:
            continue
        cid = char_lookup.get(_key(char_name))
        if not cid:
            continue
        mark_reused_char(cid)
        alias_target = _ALIASES.get(tk, tk)
        known_fid = form_lookup.get((cid, tk)) or form_lookup.get((cid, _key(alias_target)))
        if known_fid:
            mark_reused_form(cid, known_fid)
            transitions.append({"character_id": cid, "from_form": by_cid[cid]["forms"][0]["id"], "to_form": known_fid, "trigger": f"cue ({tag})"})
        else:
            fid = re.sub(r"[^a-z0-9_]+", "_", tk).strip("_")
            added_fid = ensure_form(cid, fid, tag.strip(), kind="transformation")
            transitions.append({"character_id": cid, "from_form": by_cid[cid]["forms"][0]["id"], "to_form": added_fid, "trigger": f"cue ({tag})"})

    # 3. Scan narrative transformation specs (Big Tiddy Steve, Dork 20%/80%, Nurse Franny, Awakened Fox)
    for spec in KNOWN_TRANSFORMATION_SPECS:
        for pat in spec["patterns"]:
            m = pat.search(script_text)
            if not m:
                continue
            cid = spec["character_id"]
            if cid not in by_cid:
                continue
            mark_reused_char(cid)
            fid = ensure_form(cid, spec["form_id"], spec["label"], kind=spec["kind"], after=spec["after"])
            transitions.append({"character_id": cid, "from_form": spec["after"], "to_form": fid, "trigger": m.group(0)})
            break

    # 4. Scan narrative arbitrary transformations `<Name> transforms into <FormLabel>`
    for m in _EXPLICIT_TRANSFORM_LINE_RE.finditer(script_text):
        subj_k = _key(m.group(1))
        target_label = m.group(2).strip(" .,:;!?")
        cid = char_lookup.get(subj_k)
        if not cid or not target_label:
            continue
        mark_reused_char(cid)
        tk = _key(target_label)
        alias_target = _ALIASES.get(tk, tk)
        known_fid = form_lookup.get((cid, tk)) or form_lookup.get((cid, _key(alias_target)))
        if known_fid:
            mark_reused_form(cid, known_fid)
            transitions.append({"character_id": cid, "from_form": by_cid[cid]["forms"][0]["id"], "to_form": known_fid, "trigger": m.group(0).strip()})
        else:
            fid = re.sub(r"[^a-z0-9_]+", "_", tk).strip("_")
            added_fid = ensure_form(cid, fid, target_label, kind="transformation")
            transitions.append({"character_id": cid, "from_form": by_cid[cid]["forms"][0]["id"], "to_form": added_fid, "trigger": m.group(0).strip()})

    # 5. Scan narrative entrances for Holly if mentioned cleanly in prose even before speaking.
    if _HOLLY_PROSE_RE.search(script_text):
        ensure_character("holly", "Holly")

    # Re-classify blocks against the updated FormGraphStore junctions for final speaker/form stats.
    final_payload = form_store.read()
    final_blocks = classify_saved_blocks(raw_blocks, final_payload["junctions"], initial_import=True)
    nodes = []
    edges = []
    seen_nodes = set()
    for cid in dict.fromkeys([*reused_characters, *(a["character_id"] for a in added_characters)]):
        g = next((x for x in final_payload["junctions"] if x["character_id"] == cid), None)
        if not g:
            continue
        nodes.append({"id": f"char:{cid}", "kind": "character", "character_id": cid, "label": g["forms"][0]["label"]})
        seen_nodes.add(f"char:{cid}")
        for f in g["forms"]:
            f_node = f"form:{cid}:{f['id']}"
            nodes.append({"id": f_node, "kind": f.get("kind", "form"), "character_id": cid, "form_id": f["id"], "label": f["label"]})
            seen_nodes.add(f_node)
            parent = f"form:{cid}:{f['after']}" if f.get("after") and f"form:{cid}:{f['after']}" in seen_nodes else f"char:{cid}"
            edges.append({"from": parent, "to": f_node, "kind": "has_form" if parent.startswith("char:") else "transforms_to"})

    return {
        "schema_version": 1,
        "form_graph_revision": final_payload["revision"],
        "reused_characters": reused_characters,
        "added_characters": added_characters,
        "reused_forms": reused_forms,
        "added_forms": added_forms,
        "merged_legacy_cues": merged_legacy_cues,
        "transformation_transitions": transitions,
        "speaker_blocks": [
            {"kind": b["kind"], "speaker": b.get("speaker"), "form": b.get("form"), "cue_label": b.get("cue_label")}
            for b in final_blocks
            if b.get("kind") in ("character", "unresolved")
        ],
        "graph": {"nodes": nodes, "edges": edges},
    }


def cook_with_character_graph_synthesis(
    timeline,
    form_store: FormGraphStore,
    episode_id: str,
    *,
    viewpoint: Optional[str] = None,
    branch: Optional[str] = None,
    project: Optional[str] = None,
    universe: Optional[str] = None,
) -> Dict[str, Any]:
    """Run smart character/transformation synthesis on the saved episode, then execute Cook cleanly."""
    ep = timeline.get_episode(episode_id)
    script_text = ep["script"]
    synthesis = synthesize_character_graph_for_script(script_text, form_store=form_store)
    cook_receipt = run_cook_pipeline(
        timeline,
        form_store,
        episode_id,
        viewpoint=viewpoint,
        branch=branch,
        project=project,
        universe=universe,
    )
    return {"synthesis": synthesis, "cook": cook_receipt}
