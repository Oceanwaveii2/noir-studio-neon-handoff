"""Direct Mean Girls (2004) dialogue + mined-evidence compiler for Three-Little-Bitch Rainee Digital Minds."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from story_graph.form_graph_store import FormGraphStore

DEFAULT_ALLOW_INTERVAL_MS = (0, 1_595_000)
DEFAULT_QUARANTINED = frozenset({"p04-10-hidden-witness"})
_DONOR_PROPER_NAMES = ("Regina George", "Gretchen Wieners", "Karen Smith", "Cady Heron", "Regina", "Gretchen", "Karen", "Cady", "Jason", "Aaron Samuels", "Aaron")

_SRT_TIME_RE = re.compile(
    r"^\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)
_TAG_RE = re.compile(r"<[^>]+>")
_SPEAKER_TAG_RE = re.compile(r"^([A-Z][A-Z0-9 .'\-]{1,28}):\s*(.+)$")

DEFAULT_SPLIT_ROLE_MAP = {
    "rainee-split-1": {
        "speaker": "Rainee 1",
        "split_name": "Rainee Sade",
        "short_name": "Sade",
        "display_label": "Rainee 1 · Rainee Sade",
        "mind_label": "Rainee 1 (Rainee Sade) · Frame Setter",
        "source_role": "Regina",
        "role": "Frame setter",
        "default_windows": ("p04-01-intervene", "p04-02-compliment", "p04-04-invitation", "p04-07-allegiance-display", "p04-08-adult-boundary"),
        "default_scent": "tuberose",
        "constraint": "Decide what counts, hold the floor, and turn challenges into approval conditions without importing movie plot.",
    },
    "rainee-split-2": {
        "speaker": "Rainee 2",
        "split_name": "Rainee Becky",
        "short_name": "Becky",
        "display_label": "Rainee 2 · Rainee Becky",
        "mind_label": "Rainee 2 (Rainee Becky) · Alliance Keeper",
        "source_role": "Gretchen",
        "role": "Alliance keeper",
        "default_windows": ("p04-05-ordinary-rule", "p04-06-rationale-challenged", "p04-11-corrected-in-public", "p04-01-intervene", "p04-07-allegiance-display"),
        "default_scent": "orange",
        "constraint": "Wait for the group explanation to unfold, enforce shared rules publicly, and check listener allegiance.",
    },
    "rainee-split-3": {
        "speaker": "Rainee 3",
        "split_name": "Rainee Clarie",
        "short_name": "Clarie",
        "display_label": "Rainee 3 · Rainee Clarie",
        "mind_label": "Rainee 3 (Rainee Clarie) · Literal Interrupter",
        "source_role": "Karen",
        "role": "Literal interrupter",
        "default_windows": ("p04-03-question-corrected", "p04-06-rationale-challenged", "p04-09-audience-approval", "p04-11-corrected-in-public"),
        "default_scent": "sandalwood",
        "constraint": "Drop one observable concrete detail when it punctures the excuse, even if it undercuts an ally.",
    },
}


@dataclass(frozen=True)
class SubtitleCue:
    """One timed subtitle cue parsed from an .srt file."""

    index: int
    start_ms: int
    end_ms: int
    text: str
    speaker_hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _to_ms(h: str, m: str, s: str, ms: str) -> int:
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)


def parse_srt_cues(srt_source: str | Path) -> List[SubtitleCue]:
    """Parse subtitle cues from a .srt file path or raw SRT text."""
    if isinstance(srt_source, Path) or (isinstance(srt_source, str) and "\n" not in srt_source and len(srt_source) < 260 and Path(srt_source).is_file()):
        raw = Path(srt_source).read_text(encoding="utf-8-sig", errors="replace")
    else:
        raw = str(srt_source)
    blocks = re.split(r"\r?\n\s*\r?\n", raw.strip())
    cues: List[SubtitleCue] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        time_idx = 1 if lines[0].isdigit() else 0
        if time_idx >= len(lines):
            continue
        match = _SRT_TIME_RE.match(lines[time_idx])
        if not match:
            continue
        start_ms = _to_ms(*match.groups()[:4])
        end_ms = _to_ms(*match.groups()[4:])
        body_lines = [_TAG_RE.sub("", l).strip() for l in lines[time_idx + 1:]]
        text = " ".join(part for part in body_lines if part).strip()
        if not text:
            continue
        speaker_hint = None
        sm = _SPEAKER_TAG_RE.match(text)
        if sm:
            speaker_hint = sm.group(1).strip().title()
        cues.append(
            SubtitleCue(
                index=int(lines[0]) if lines[0].isdigit() else len(cues) + 1,
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                speaker_hint=speaker_hint,
            )
        )
    return cues


def anonymize_donor_text(text: str) -> str:
    """Strip donor movie character proper names so Noir prompts transfer behavior rather than film cast."""
    out = str(text or "")
    for name in _DONOR_PROPER_NAMES:
        out = re.sub(rf"\b{re.escape(name)}\b(?:'s)?", "the speaker", out, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", out).strip()


def _dialogue_mechanics(cues: Sequence[SubtitleCue]) -> Dict[str, Any]:
    if not cues:
        return {"cue_count": 0, "avg_words": 0.0, "question_ratio": 0.0, "short_turn_ratio": 0.0}
    words = [len(re.findall(r"[A-Za-z0-9']+", c.text)) for c in cues]
    questions = sum(1 for c in cues if "?" in c.text)
    short_turns = sum(1 for w in words if w <= 6)
    return {
        "cue_count": len(cues),
        "avg_words": round(sum(words) / len(cues), 2),
        "question_ratio": round(questions / len(cues), 3),
        "short_turn_ratio": round(short_turns / len(cues), 3),
    }


def extract_admitted_dialogue_windows(
    linked_evidence: Dict[str, Any],
    *,
    srt_cues: Sequence[SubtitleCue] = (),
    allow_interval_ms: Tuple[int, int] = DEFAULT_ALLOW_INTERVAL_MS,
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """Filter movie evidence strictly to admitted pre-betrayal windows and map subtitle timing/rhythm."""
    low_ms, high_ms = allow_interval_ms
    admitted = set(linked_evidence.get("admitted_ids") or ())
    quarantined = set(linked_evidence.get("quarantined_ids") or ()) | DEFAULT_QUARANTINED
    eligible_ids = admitted - quarantined

    windows: Dict[str, Dict[str, Any]] = {}
    rejected: List[str] = []
    for row in linked_evidence.get("moments") or ():
        mid = row.get("id")
        span = row.get("span_ms") or [0, 0]
        if not mid or mid in quarantined or (admitted and mid not in eligible_ids):
            rejected.append(str(mid or "unknown"))
            continue
        if row.get("eligibility") != "transfer" or len(span) != 2:
            rejected.append(str(mid))
            continue
        a, b = int(span[0]), int(span[1])
        if not (low_ms <= a < b <= high_ms):
            rejected.append(str(mid))
            continue
        matched_cues = [c for c in srt_cues if a <= c.end_ms and c.start_ms <= b]
        windows[mid] = {
            "id": mid,
            "window": row.get("window", ""),
            "span_ms": [a, b],
            "actors": list(row.get("actors") or ()),
            "pressure": anonymize_donor_text(row.get("pressure", "")),
            "performed": anonymize_donor_text(row.get("performed", "")),
            "power_change": anonymize_donor_text(row.get("power_change", "")),
            "audio_note": row.get("audio_note", ""),
            "mechanics": _dialogue_mechanics(matched_cues),
            "cue_timestamps_ms": [[c.start_ms, c.end_ms] for c in matched_cues],
            "frame_count": len(row.get("frame_evidence") or ()),
        }
    return windows, rejected


def build_three_little_bitches_minds(
    mean_girls_dir: Optional[Path] = None,
    *,
    linked_evidence: Optional[Dict[str, Any]] = None,
    donor_override: Optional[Dict[str, Any]] = None,
    srt_cues: Optional[Sequence[SubtitleCue]] = None,
    scent_rules: Optional[Dict[str, Any]] = None,
    timing_cues: Sequence[str] = (),
    include_movie_dir: bool = True,
) -> Dict[str, Any]:
    """Build distinct graph-ready Digital Mind definitions for rainee-split-1/2/3 from Mean Girls evidence."""
    root = Path(mean_girls_dir) if mean_girls_dir is not None else (
        Path(__file__).resolve().parents[1] / "deliverables" / "NOIR_FX06_GAG_COLLECTION_20261116" / "Mean Girls (2004)"
    )
    if linked_evidence is None and include_movie_dir and (root / "Mined Evidence" / "linked_evidence.json").is_file():
        linked_evidence = json.loads((root / "Mined Evidence" / "linked_evidence.json").read_text(encoding="utf-8"))
    if donor_override is None and include_movie_dir and (root / "Mined Evidence" / "donor_override.json").is_file():
        donor_override = json.loads((root / "Mined Evidence" / "donor_override.json").read_text(encoding="utf-8"))
    if srt_cues is None and include_movie_dir and (root / "Transcript" / "Full Film.en.srt").is_file():
        srt_cues = parse_srt_cues(root / "Transcript" / "Full Film.en.srt")

    linked_evidence = linked_evidence or {"admitted_ids": [], "quarantined_ids": list(DEFAULT_QUARANTINED), "moments": []}
    donor_override = donor_override or {}
    srt_cues = list(srt_cues or ())

    interval = tuple(donor_override.get("access", {}).get("allow_interval_ms") or DEFAULT_ALLOW_INTERVAL_MS)
    if len(interval) != 2:
        interval = DEFAULT_ALLOW_INTERVAL_MS
    windows, rejected = extract_admitted_dialogue_windows(
        linked_evidence,
        srt_cues=srt_cues,
        allow_interval_ms=(int(interval[0]), int(interval[1])),
    )

    scent_by_form: Dict[str, Dict[str, Any]] = {}
    for row in (scent_rules or {}).get("rules", ()):
        if isinstance(row, dict) and row.get("form"):
            scent_by_form[row["form"]] = row

    cards_by_target = {c["target"]: c for c in donor_override.get("actor_cards", ()) if isinstance(c, dict) and c.get("target")}
    built_minds: List[Dict[str, Any]] = []
    for form_id, spec in DEFAULT_SPLIT_ROLE_MAP.items():
        card = cards_by_target.get(form_id, {})
        tendencies = []
        evidence_ids = set()
        for move in card.get("tendencies", ()):
            ev = [eid for eid in (move.get("evidence") or ()) if eid in windows]
            if not ev and move.get("evidence"):
                continue
            evidence_ids.update(ev)
            tendencies.append({
                "when": anonymize_donor_text(move.get("when", "")),
                "try": anonymize_donor_text(move.get("try", "")),
                "evidence": ev,
            })
        if not tendencies:
            ev = [eid for eid in spec["default_windows"] if eid in windows]
            evidence_ids.update(ev)
            tendencies.append({
                "when": f"acting as {spec['role'].lower()} in an active three-way split exchange",
                "try": spec["constraint"],
                "evidence": ev,
            })

        matched_windows = [windows[eid] for eid in sorted(evidence_ids) if eid in windows]
        if not matched_windows:
            matched_windows = [windows[eid] for eid in spec["default_windows"] if eid in windows]
        role_cues = [
            c for c in srt_cues
            if any(w["span_ms"][0] <= c.end_ms and c.start_ms <= w["span_ms"][1] for w in matched_windows)
        ]
        mech = _dialogue_mechanics(role_cues)
        scent_row = scent_by_form.get(form_id, {})
        scent_name = scent_row.get("scent", spec["default_scent"])
        scent_perfume = scent_row.get("perfume", "")
        behavior_lines = [f"Split identity: {spec['display_label']}. Role: {spec['role']}. {spec['constraint']}"]
        for t in tendencies:
            behavior_lines.append(f"When {t['when']}: {t['try']}")
        if mech["cue_count"]:
            behavior_lines.append(
                f"Film rhythm ({len(matched_windows)} admitted windows, {mech['cue_count']} SRT cues): "
                f"avg {mech['avg_words']} words/cue, {int(mech['short_turn_ratio'] * 100)}% tight turns, "
                f"{int(mech['question_ratio'] * 100)}% challenge questions."
            )
        behavior_lines.append(f"Local scent rule on personal release: {scent_name}" + (f" ({scent_perfume})" if scent_perfume else "") + ".")
        for hint in timing_cues:
            behavior_lines.append(f"Timing note: {hint}")

        built_minds.append({
            "form_id": form_id,
            "character_id": "rainee",
            "speaker": spec["speaker"],
            "split_name": spec["split_name"],
            "short_name": spec["short_name"],
            "display_label": spec["display_label"],
            "name_aliases": [spec["speaker"], spec["split_name"], spec["short_name"], f"{spec['speaker']} ({spec['split_name']})"],
            "mind_label": spec["mind_label"],
            "role": spec["role"],
            "constraint": spec["constraint"],
            "scent": scent_name,
            "perfume": scent_perfume,
            "tendencies": tendencies,
            "evidence_windows": [w["id"] for w in matched_windows],
            "dialogue_mechanics": mech,
            "behavior": "\n".join(behavior_lines),
        })

    relationships = []
    for edge in donor_override.get("optional_local_relationship_edges", ()):
        ev = [eid for eid in (edge.get("evidence") or ()) if eid in windows]
        if ev and edge.get("from") in DEFAULT_SPLIT_ROLE_MAP and edge.get("to") in DEFAULT_SPLIT_ROLE_MAP:
            relationships.append({
                "from": edge["from"],
                "to": edge["to"],
                "context": anonymize_donor_text(edge.get("context", "")),
                "effect": anonymize_donor_text(edge.get("effect", "")),
                "evidence": ev,
            })

    digest = hashlib.sha256(
        json.dumps({"minds": built_minds, "relationships": relationships}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "source": "mean-girls-2004",
        "allow_interval_ms": list(interval),
        "admitted_window_count": len(windows),
        "quarantined_or_rejected": sorted(set(rejected)),
        "srt_cue_count": len(srt_cues),
        "minds": built_minds,
        "relationships": relationships,
        "digest_sha256": digest,
    }


def attach_mean_girls_minds_to_form_graph(
    form_store: FormGraphStore,
    compiled_minds: Dict[str, Any],
) -> Dict[str, Any]:
    """Ensure rainee-split-1/2/3 forms + Digital Mind nodes exist in FormGraphStore and bind behavior cards."""
    payload = form_store.read()
    revision = payload["revision"]
    rainee_group = next((g for g in payload["junctions"] if g["character_id"] == "rainee"), None)
    if rainee_group is None:
        raise ValueError("Missing rainee character junction in FormGraphStore.")

    existing_forms = {f["id"]: f for f in rainee_group["forms"]}
    attached_ports: List[Dict[str, Any]] = []

    for mind in compiled_minds.get("minds", ()):
        fid = mind["form_id"]
        if fid not in existing_forms:
            payload = form_store.change({
                "action": "add_form",
                "revision": revision,
                "character": "rainee",
                "form_id": fid,
                "label": mind.get("split_name") or mind["speaker"],
                "kind": "transformation",
                "after": "rainee",
            })
            revision = payload["revision"]
            rainee_group = next(g for g in payload["junctions"] if g["character_id"] == "rainee")
            existing_forms = {f["id"]: f for f in rainee_group["forms"]}

        form_row = existing_forms[fid]
        port_id = form_row["port_id"]
        if not form_row.get("link"):
            # Reuse existing node matching mind_label if present, otherwise create and link one.
            existing_node = next(
                (n for n in payload.get("nodes", ()) if n.get("kind") == "digital_mind" and n.get("label", "").casefold() == mind["mind_label"].casefold()),
                None,
            )
            if existing_node:
                payload = form_store.change({
                    "action": "set_link",
                    "revision": revision,
                    "port": port_id,
                    "node_id": existing_node["id"],
                })
            else:
                payload = form_store.change({
                    "action": "create_mind_link",
                    "revision": revision,
                    "port": port_id,
                    "label": mind["mind_label"],
                    "kind": "digital_mind",
                })
            revision = payload["revision"]

        data_node_id = f"data:{port_id}"
        content = {
            "text_fields": {
                "behavior": mind["behavior"],
                "role": mind["role"],
                "scent": mind["scent"],
                "constraint": mind["constraint"],
                "split_name": mind.get("split_name", mind["speaker"]),
                "display_label": mind.get("display_label", mind["speaker"]),
            },
            "structured_data": {
                "source": "mean-girls-2004",
                "split_name": mind.get("split_name", mind["speaker"]),
                "short_name": mind.get("short_name", ""),
                "name_aliases": mind.get("name_aliases", [mind["speaker"]]),
                "evidence_windows": mind["evidence_windows"],
                "dialogue_mechanics": mind["dialogue_mechanics"],
                "tendencies": mind["tendencies"],
            },
        }
        payload = form_store.change({
            "action": "save_node_data",
            "revision": revision,
            "character": "rainee",
            "node": data_node_id,
            "content": content,
        })
        revision = payload["revision"]
        attached_ports.append({
            "form_id": fid,
            "port_id": port_id,
            "split_name": mind.get("split_name", mind["speaker"]),
            "display_label": mind.get("display_label", mind["speaker"]),
            "data_node_id": data_node_id,
            "evidence_windows": mind["evidence_windows"],
        })

    peter_form = existing_forms.get("peter_griffin_celestial_variant")
    peter_node_receipt = None
    if peter_form is not None:
        peter_port = peter_form["port_id"]
        if not peter_form.get("link"):
            existing_peter_node = next(
                (
                    n for n in payload.get("nodes", ())
                    if n.get("kind") == "digital_mind"
                    and ("rainee peter" in n.get("label", "").casefold() or "peter" in n.get("id", "").casefold())
                ),
                None,
            )
            if existing_peter_node:
                payload = form_store.change({
                    "action": "set_link",
                    "revision": revision,
                    "port": peter_port,
                    "node_id": existing_peter_node["id"],
                })
            else:
                payload = form_store.change({
                    "action": "create_mind_link",
                    "revision": revision,
                    "port": peter_port,
                    "label": "Rainee Peter · Mean Girls Transformation Hub",
                    "kind": "digital_mind",
                })
            revision = payload["revision"]

        peter_data_node = f"data:{peter_port}"
        split_summary = "; ".join(
            f"{m.get('split_name', m['speaker'])} ({m['role']}, scent={m['scent']})"
            for m in compiled_minds.get("minds", ())
        )
        all_windows = sorted({
            wid
            for m in compiled_minds.get("minds", ())
            for wid in m.get("evidence_windows", ())
        })
        peter_behavior = "\n".join([
            "TRANSFORMATION MIND HUB (stored on Peter Griffin section):",
            f"Linked split manifestations: {split_summary}.",
            "When Rainee comes downstairs right after the bathroom scene, first-stage destabilization splits her into the Three Little Bitches using this attached Mean Girls (2004) + Pretty Girl Fart data.",
            "After Francine reunites them, Rainee transforms into Rainee Peter Griffen briefly, farts to blow Haley across the room, uses her power to turn Francine into Nurse Franny, and then destabilizes back into the same Three Little Bitches from another fart, repeating the gag.",
        ])
        peter_content = {
            "text_fields": {
                "behavior": peter_behavior,
                "role": "Transformation & Three-Little-Bitches Mean Girls Hub",
                "mean_girls_source": "mean-girls-2004",
                "split_manifestations": split_summary,
            },
            "structured_data": {
                "source": "mean-girls-2004",
                "transformation_form": "peter_griffin_celestial_variant",
                "split_forms": [m["form_id"] for m in compiled_minds.get("minds", ())],
                "split_names": [m.get("split_name", m["speaker"]) for m in compiled_minds.get("minds", ())],
                "scents": [m.get("scent") for m in compiled_minds.get("minds", ())],
                "admitted_evidence_windows": all_windows,
                "admitted_window_count": compiled_minds.get("admitted_window_count", 0),
                "srt_cue_count": compiled_minds.get("srt_cue_count", 0),
            },
        }
        payload = form_store.change({
            "action": "save_node_data",
            "revision": revision,
            "character": "rainee",
            "node": peter_data_node,
            "content": peter_content,
        })
        revision = payload["revision"]
        peter_node_receipt = {
            "form_id": "peter_griffin_celestial_variant",
            "port_id": peter_port,
            "data_node_id": peter_data_node,
            "evidence_windows": all_windows,
        }

    return {
        "revision": revision,
        "attached": attached_ports,
        "peter_node": peter_node_receipt,
        "mind_digest_sha256": compiled_minds.get("digest_sha256"),
    }
