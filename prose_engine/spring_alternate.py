"""Editable Alternative Spring Break Scene 4 (Rainee destabilizes into Three Little Bitches + fart-daughter-away + leaving variants)."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_graph.form_graph_store import FormGraphStore
from story_graph.fx06_scene import PERFUME_LINE

SPLIT_FORMS = ("rainee-split-1", "rainee-split-2", "rainee-split-3")
SPLIT_SPEAKERS = ("Rainee 1", "Rainee 2", "Rainee 3")
SPLIT_NAMED_SPEAKERS = ("Rainee Sade", "Rainee Becky", "Rainee Clarie")
SPLIT_CUE_GROUPS = (
    ("Rainee 1", "Rainee Sade", "Rainee 1 (Rainee Sade)", "Rainee 1 · Rainee Sade", "Sade"),
    ("Rainee 2", "Rainee Becky", "Rainee 2 (Rainee Becky)", "Rainee 2 · Rainee Becky", "Becky"),
    ("Rainee 3", "Rainee Clarie", "Rainee 3 (Rainee Clarie)", "Rainee 3 · Rainee Clarie", "Clarie"),
)
CANONICAL_PETER_CUE = "Rainee Peter Griffen"
LEAVING_MODES = ("relapse", "clothes")

_BARE_PETER_RE = re.compile(
    r"(?:^|\n)\s*Peter\s*:|\b(?:she\s+was\s+Peter|became\s+Peter|as\s+Peter(?:\s+Griffin)?\b(?!\s+Griffen))",
    re.IGNORECASE,
)
_SHOCKER_RE = re.compile(r"\bshocker\b", re.IGNORECASE)


def _has_cue(text: str, aliases: Sequence[str]) -> bool:
    pat = re.compile(
        r"(?:^|\n)\s*(?:\*\*)?(?:"
        + "|".join(re.escape(a) for a in aliases)
        + r")(?:\s*\([^)\r\n]*\))?\s*(?:\*\*)?\s*:",
        re.IGNORECASE,
    )
    return bool(pat.search(text))


@dataclass(frozen=True)
class Scene4BeatSpec:
    beat_id: str
    phase: str
    active_rainee_forms: Tuple[str, ...]
    allowed_speakers: Tuple[str, ...]
    scents_active: bool
    summary: str


def alternate_beat_sequence(
    leaving_mode: str = "relapse",
    *,
    sequence_mode: str = "downstairs_peter_split",
) -> List[Scene4BeatSpec]:
    """Return the verified state sequence for Scene 4 (destabilize + fart blasts + roast) and alternative departure."""
    if leaving_mode not in LEAVING_MODES:
        raise ValueError(f"Unsupported Spring Break leaving mode: {leaving_mode}")
    if sequence_mode == "downstairs_peter_split":
        beats = [
            Scene4BeatSpec(
                beat_id="downstairs-first-split",
                phase="split",
                active_rainee_forms=SPLIT_FORMS,
                allowed_speakers=(*SPLIT_SPEAKERS, "Haley", "Francine", "Stella"),
                scents_active=True,
                summary=(
                    "Right after the bathroom scene, Rainee comes downstairs into the living room; at the moment she "
                    "would turn into Peter, she farts and splits into Rainee Sade, Rainee Becky, and Rainee Clarie, "
                    "driven by the Mean Girls mind attached to Peter's transformation node, and they roast Haley."
                ),
            ),
            Scene4BeatSpec(
                beat_id="francine-reunion",
                phase="reunion",
                active_rainee_forms=("rainee",),
                allowed_speakers=("Francine", "Rainee", "Haley", "Stella"),
                scents_active=False,
                summary="Francine puts the three Rainees back together into one base Rainee.",
            ),
            Scene4BeatSpec(
                beat_id="peter-brief-and-first-blast",
                phase="peter_active",
                active_rainee_forms=("peter_griffin_celestial_variant",),
                allowed_speakers=("Francine", CANONICAL_PETER_CUE, "Haley", "Stella"),
                scents_active=False,
                summary=(
                    "Reunited Rainee transforms into Rainee Peter Griffen briefly, then rips a massive fart that "
                    "blows Haley away across the living room."
                ),
            ),
            Scene4BeatSpec(
                beat_id="nurse-franny-via-rainee-power",
                phase="nurse_active",
                active_rainee_forms=("peter_griffin_celestial_variant", "nurse_pamela_franny_anderson"),
                allowed_speakers=("Francine", "Nurse Franny", CANONICAL_PETER_CUE, "Haley", "Stella"),
                scents_active=False,
                summary=(
                    "After Haley is blown away, Francine transforms into Nurse Franny via Rainee Peter Griffen's "
                    "powers (silver nanites / finger-gun zap)."
                ),
            ),
            Scene4BeatSpec(
                beat_id="destabilize-repeat-gag",
                phase="relapse_roast",
                active_rainee_forms=SPLIT_FORMS,
                allowed_speakers=("Nurse Franny", *SPLIT_SPEAKERS, "Haley", "Stella"),
                scents_active=True,
                summary=(
                    "Rainee Peter Griffen destabilizes from another fart back into the Three Little Bitches "
                    "(Rainee Sade, Rainee Becky, Rainee Clarie; Peter gone), repeating the fart gag with tuberose, "
                    "orange, and sandalwood scents, blowing Haley around, and delivering a Mean-Girls roast."
                ),
            ),
        ]
    else:
        beats = [
            Scene4BeatSpec(
                beat_id="first-split",
                phase="split",
                active_rainee_forms=SPLIT_FORMS,
                allowed_speakers=(*SPLIT_SPEAKERS, "Haley"),
                scents_active=True,
                summary="Rainee splits behind the bathroom door into three distinct manifestations.",
            ),
            Scene4BeatSpec(
                beat_id="francine-reunion",
                phase="reunion",
                active_rainee_forms=("rainee",),
                allowed_speakers=("Francine", "Rainee"),
                scents_active=False,
                summary="Regular Francine intervenes by voice alone (no Shocker) and reunites the three into base Rainee.",
            ),
            Scene4BeatSpec(
                beat_id="peter-and-nurse-franny",
                phase="peter_active",
                active_rainee_forms=("peter_griffin_celestial_variant",),
                allowed_speakers=("Francine", "Nurse Franny", CANONICAL_PETER_CUE, "Haley"),
                scents_active=False,
                summary=(
                    "Only after reunion does Rainee swell into Rainee Peter Griffen; spouse Francine laughs, asks for "
                    "Nurse Franny, and Rainee Peter Griffen blasts Haley down the hall with the first fart."
                ),
            ),
            Scene4BeatSpec(
                beat_id="destabilize-and-fart-daughter-away",
                phase="relapse_roast",
                active_rainee_forms=SPLIT_FORMS,
                allowed_speakers=("Nurse Franny", *SPLIT_SPEAKERS, "Haley"),
                scents_active=True,
                summary=(
                    "Rainee Peter Griffen destabilizes back into the same Three Little Bitches (Peter gone); together they "
                    "unleash the second fart blast (tuberose, orange, sandalwood) to fart their bitch daughter Haley farther "
                    "down the hall, then deliver a three-voice Mean-Girls-derived roast."
                ),
            ),
        ]
    if leaving_mode == "relapse":
        beats.append(
            Scene4BeatSpec(
                beat_id="leaving-hallway-driveway",
                phase="departure",
                active_rainee_forms=SPLIT_FORMS,
                allowed_speakers=("Nurse Franny", *SPLIT_SPEAKERS, "Haley", "Stella"),
                scents_active=False,
                summary=(
                    "Alternative leaving (Hallway Tag): Nurse Franny rounds up the three Rainees, hands Haley keys "
                    "and three lasagna trays, and drives the red sedan away with Haley and Stella remaining."
                ),
            )
        )
    else:
        beats.append(
            Scene4BeatSpec(
                beat_id="leaving-clothes-and-car",
                phase="departure",
                active_rainee_forms=SPLIT_FORMS,
                allowed_speakers=("Nurse Franny", *SPLIT_SPEAKERS, "Haley", "Stella"),
                scents_active=False,
                summary=(
                    "Alternative leaving (Clothes & Car): Nurse Franny marches the three Rainees upstairs to pack outfits "
                    "in a red overnight bag (arguing with Mean Girls tactics), hands Haley keys & three lasagna trays, "
                    "and drives off in the red sedan."
                ),
            )
        )
    return beats


def resolve_live_split_minds(
    compiled_minds: Dict[str, Any],
    form_store: Optional[FormGraphStore] = None,
) -> List[Dict[str, Any]]:
    """Resolve Three-Little-Bitch Minds, prioritizing live FormGraphStore node_data (both Peter hub and split forms)."""
    live_behaviors: Dict[str, str] = {}
    peter_hub_behavior = ""
    if form_store is not None:
        payload = form_store.read()
        rainee = next((g for g in payload.get("junctions", ()) if g["character_id"] == "rainee"), None)
        if rainee:
            node_data = rainee.get("node_data", {})
            for form in rainee.get("forms", ()):
                fid = form["id"]
                if fid in SPLIT_FORMS and form.get("link"):
                    entry = node_data.get("data:" + form["port_id"], {})
                    beh = (entry.get("text_fields") or {}).get("behavior", "")
                    if isinstance(beh, str) and beh.strip():
                        live_behaviors[fid] = beh.strip()
                elif fid == "peter_griffin_celestial_variant":
                    entry = node_data.get("data:" + form["port_id"], {})
                    beh = (entry.get("text_fields") or {}).get("behavior", "")
                    if isinstance(beh, str) and beh.strip():
                        peter_hub_behavior = beh.strip()

    resolved = []
    for mind in compiled_minds.get("minds", ()):
        fid = mind["form_id"]
        card = dict(mind)
        if fid in live_behaviors:
            card["behavior"] = live_behaviors[fid]
            card["source_binding"] = "form_graph_live_node"
        else:
            card["source_binding"] = "mean_girls_compiled"
        if peter_hub_behavior:
            card["peter_hub_behavior"] = peter_hub_behavior
        resolved.append(card)
    return resolved


def build_alternate_spring_packet(
    prefix_text: str,
    editable_seed_text: str,
    suffix_text: str,
    compiled_minds: Dict[str, Any],
    *,
    form_store: Optional[FormGraphStore] = None,
    leaving_mode: str = "relapse",
    sequence_mode: str = "bathroom_door",
    timing_notes: Sequence[str] = (),
    locked_cue: str = PERFUME_LINE,
    full_story: bool = False,
    require_named_splits: bool = False,
) -> Dict[str, Any]:
    """Assemble an editable Scene 4 + departure or full-story writer packet keeping Haley's cue locked."""
    if not full_story and locked_cue not in prefix_text:
        raise ValueError("Frozen prefix must contain Haley's exact locked perfume cue.")
    beats = alternate_beat_sequence(leaving_mode, sequence_mode=sequence_mode)
    live_minds = resolve_live_split_minds(compiled_minds, form_store=form_store)
    peter_hub = next((m.get("peter_hub_behavior") for m in live_minds if m.get("peter_hub_behavior")), "")
    full_text = prefix_text + editable_seed_text + suffix_text
    edit_start = len(prefix_text)
    edit_end = edit_start + len(editable_seed_text)
    lock_src = prefix_text if (not full_story or locked_cue in prefix_text) else editable_seed_text
    lock_base = 0 if (not full_story or locked_cue in prefix_text) else edit_start
    if locked_cue not in lock_src:
        raise ValueError("Episode seed must contain Haley's exact locked perfume cue.")
    lock_start = lock_base + lock_src.index(locked_cue)
    lock_end = lock_start + len(locked_cue)

    lines = [
        f"ALTERNATE SPRING BREAK {'FULL STORY' if full_story else 'SCENES 4-6'} ({leaving_mode.upper()} · {sequence_mode})",
        f"Preserve Haley's exact locked line: {locked_cue}",
        f"Canonical transformed form name: {CANONICAL_PETER_CUE} (never bare 'Peter' as standalone cue or 'she was Peter').",
        "No Shocker prop. First split precedes reunion; Rainee Peter Griffen appears only after reunion; destabilize back to Rainee Sade / Rainee Becky / Rainee Clarie.",
        "",
        "Beat sequence:",
    ]
    for b in beats:
        lines.append(f"- [{b.beat_id}] forms={','.join(b.active_rainee_forms)} speakers={','.join(b.allowed_speakers)} scents={b.scents_active}: {b.summary}")
    if peter_hub:
        lines.append("")
        lines.append("Peter Griffin Transformation Node (FormGraph data:character:rainee:form:peter_griffin_celestial_variant):")
        lines.append(peter_hub)
    lines.append("")
    lines.append("Active Mean-Girls-derived Digital Minds (Rainee 1 · Sade / Rainee 2 · Becky / Rainee 3 · Clarie):")
    for m in live_minds:
        lines.append(f"* {m.get('display_label') or m['speaker']} ({m['form_id']}, name={m.get('split_name', m['speaker'])}, role={m['role']}, scent={m['scent']}):")
        lines.append(f"  {m['behavior']}")
    if timing_notes:
        lines.append("")
        lines.append("Fart Media delivery & pause cues:")
        for note in timing_notes:
            lines.append(f"- {note}")

    prompt = "\n".join(lines)
    return {
        "schema_version": 1,
        "episode": f"spring-break-three-little-bitches-{leaving_mode}",
        "leaving_mode": leaving_mode,
        "sequence_mode": sequence_mode,
        "full_story": full_story,
        "require_named_splits": require_named_splits,
        "locked_cue": locked_cue,
        "full_text": full_text,
        "editable_slot": {"start": edit_start, "end": edit_end, "protection": 25},
        "locked_spans": [
            {"id": "haley-exact-cue", "start": lock_start, "end": lock_end, "value": 100, "hard": True},
            {"id": "roger-suffix", "start": edit_end, "end": len(full_text), "value": 100, "hard": True},
        ],
        "prefix_sha256": hashlib.sha256(prefix_text.encode("utf-8")).hexdigest(),
        "suffix_sha256": hashlib.sha256(suffix_text.encode("utf-8")).hexdigest(),
        "beats": [
            {
                "beat_id": b.beat_id,
                "phase": b.phase,
                "active_rainee_forms": list(b.active_rainee_forms),
                "allowed_speakers": list(b.allowed_speakers),
                "scents_active": b.scents_active,
                "summary": b.summary,
            }
            for b in beats
        ],
        "minds": live_minds,
        "relationships": compiled_minds.get("relationships", ()),
        "writer_brief": prompt,
        "brief_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }


def validate_alternate_spring_candidate(candidate_text: str, packet: Dict[str, Any]) -> Dict[str, Any]:
    """Validate candidate Scene 4 + departure or full-story prose for form isolation, names, scents, and structure."""
    issues: List[str] = []
    if _SHOCKER_RE.search(candidate_text):
        issues.append("Shocker prop is forbidden in the alternate Three Little Bitches reunion.")
    if _BARE_PETER_RE.search(candidate_text):
        issues.append(f"Use canonical '{CANONICAL_PETER_CUE}' instead of bare 'Peter' shorthand.")
    if CANONICAL_PETER_CUE not in candidate_text:
        issues.append(f"Candidate must depict '{CANONICAL_PETER_CUE}' before destabilizing.")
    # Strip `### SCENE ...` heading lines when checking causal phase offsets so a title like
    # `### SCENE 4: ... AND RAINEE PETER GRIFFEN` doesn't masquerade as an early transformation.
    body_only = re.sub(r"(?m)^#{1,6}\s+SCENE\b[^\n]*", lambda m: " " * len(m.group(0)), candidate_text)
    body_low = body_only.casefold()
    low = candidate_text.casefold()
    if not re.search(
        r"\b(destabiliz\w*|split(?:s|ting)?\s+back|shatter\w*\s+back|popp(?:ed|ing)?\s+(?:and\s+)?(?:destabiliz|into\s+smoke)|three\s+rainees?\s+(?:were|are)\s+back)\b",
        body_low,
    ):
        issues.append("Candidate must show Rainee Peter Griffen destabilizing back into the three Rainees.")
    for group in SPLIT_CUE_GROUPS:
        if not _has_cue(candidate_text, group):
            issues.append(f"Missing distinct speaker turn for {group[0]} / {group[1]}.")
    if packet.get("require_named_splits"):
        for short, named in (("sade", "Rainee Sade"), ("becky", "Rainee Becky"), ("clarie", "Rainee Clarie")):
            if short not in low or not _has_cue(candidate_text, (named, f"Rainee 1 ({named})", f"Rainee 2 ({named})", f"Rainee 3 ({named})", short.title())):
                issues.append(f"Add '{named}' to the split character's name and speaker cues.")
    missing_scents = [m["scent"] for m in packet.get("minds", ()) if m.get("scent") and m["scent"].casefold() not in low]
    if missing_scents:
        issues.append(f"Missing local release scent signature(s): {', '.join(missing_scents)}.")
    if "fart" not in low and "blast" not in low and "gust" not in low:
        issues.append("Candidate must stage the fart/gust blast driving Haley down the hall.")
    if "key" not in low or "lasagna" not in low:
        issues.append("Leaving beat must account for the house keys and lasagna trays left with Haley.")
    if packet.get("leaving_mode") == "clothes" and "bag" not in low and "clothes" not in low and "outfit" not in low:
        issues.append("Clothes leaving mode must depict packing the overnight bag / clothes.")
    if packet.get("full_story"):
        locked_cue = packet.get("locked_cue", PERFUME_LINE)
        if locked_cue not in candidate_text:
            issues.append(f"Full story must preserve Haley's exact locked cue: {locked_cue}")
        for num in ("1", "2", "3", "4", "6", "7"):
            if not re.search(rf"###\s+SCENE\s+{num}\b", candidate_text, re.IGNORECASE):
                issues.append(f"Full story missing heading `### SCENE {num}`.")
        if not re.search(r"###\s+SCENE\s+5[A]?\b", candidate_text, re.IGNORECASE):
            issues.append("Full story missing heading `### SCENE 5` or `### SCENE 5A`.")
        if "roger" not in low or "rutgers" not in low:
            issues.append("Full story Scene 7 must depict Roger's Rutgers Spring Break takeover.")

    # Verify exact causal phase order:
    # Rainee splits -> roasts Hayley -> Francine reunites -> transforms into Rainee Peter Griffen
    # -> second fart/blast -> destabilizes back into Sade/Becky/Clarie (with no post-destabilize Peter cue).
    peter_pos = body_low.find("rainee peter griffen")
    if peter_pos != -1:
        before_peter = body_only[:peter_pos]
        if not any(_has_cue(before_peter, group) for group in SPLIT_CUE_GROUPS):
            issues.append(
                "Causal order violation: Rainee Sade / Becky / Clarie split and roast must occur BEFORE "
                "Rainee transforms into Rainee Peter Griffen."
            )
        after_peter = body_only[peter_pos:]
        after_peter_low = after_peter.casefold()
        destab_match = re.search(
            r"\b(destabiliz\w*|split(?:s|ting)?\s+back|shatter\w*\s+back|popp(?:ed|ing)?\s+(?:and\s+)?destabiliz\w*|popp\w*\s+into\s+smoke|three\s+rainees?\s+(?:were|are)\s+back)\b",
            after_peter_low,
        )
        if destab_match is None:
            issues.append(
                "Causal order violation: destabilization back into the three bitches must occur AFTER "
                "Rainee Peter Griffen appears."
            )
        else:
            after_destab = after_peter[destab_match.end():]
            if not any(_has_cue(after_destab, group) for group in SPLIT_CUE_GROUPS):
                issues.append(
                    "Causal order violation: after destabilizing, Rainee Sade / Becky / Clarie must take active turns."
                )
            if re.search(r"(?m)^\s*(?:\*\*)?Rainee\s+Peter\s+Griffen(?:\*\*)?\s*:", after_destab, re.IGNORECASE):
                issues.append(
                    "Morph state violation: Rainee Peter Griffen cannot speak after destabilizing back into the three."
                )
        if packet.get("sequence_mode") == "downstairs_peter_split":
            nurse_cue = re.search(r"(?m)^\s*(?:\*\*)?Nurse\s+(?:Pamela\s+)?Franny(?:\s+Anderson)?(?:\*\*)?\s*:", body_only, re.IGNORECASE)
            if nurse_cue is None:
                issues.append("Downstairs sequence requires Francine turning into Nurse Franny via Rainee's power.")
            else:
                if nurse_cue.start() <= peter_pos:
                    issues.append("Causal order violation: Rainee Peter Griffen must transform and blast BEFORE Nurse Franny takes her morph turn.")
                between_peter_and_nurse = body_only[peter_pos:nurse_cue.start()].casefold()
                if not re.search(
                    r"\b(?:fart\w*|blast\w*|gust\w*|br+a+p+|ka+b+o+m+|pf+t+|shockwave|pressure\s+wave|gale)\b",
                    between_peter_and_nurse,
                ):
                    issues.append("Causal order violation: Rainee Peter Griffen must fart and blow Haley away BEFORE turning Francine into Nurse Franny.")
                if destab_match is not None and (peter_pos + destab_match.start()) < nurse_cue.start():
                    issues.append("Causal order violation: Rainee Peter Griffen must destabilize into the Three Little Bitches AFTER turning Francine into Nurse Franny.")

    # Morph-identity guard: Nurse Franny is Francine's own morph, never a separate person she calls out to.
    if re.search(r'"[^"]*\bNurse\s+Franny\s*,\s*(?:get|come|bring|help|hurry)\b[^"]*"', candidate_text, re.IGNORECASE):
        issues.append(
            "Morph identity violation: Francine and Nurse Franny are the same person (Francine's morph); "
            "Francine cannot summon Nurse Franny as a separate character."
        )

    # Duplicate locked-line guard: exact hard-locked cue must appear at most once in full stories,
    # and zero times inside replacement Scenes 4-6 slots (where Scene 3 is already frozen in prefix).
    locked_cue = packet.get("locked_cue", PERFUME_LINE)
    if locked_cue:
        if not packet.get("full_story") and locked_cue in candidate_text:
            issues.append(
                f"Duplicate locked line violation: '{locked_cue}' is already frozen in Scene 3 and must NOT be repeated inside Scenes 4–6."
            )
        elif candidate_text.count(locked_cue) > 1:
            issues.append(
                f"Duplicate locked line violation: '{locked_cue}' appeared {candidate_text.count(locked_cue)} times (must appear once)."
            )

    # Anti-condensation expansion floor when requested by the packet.
    min_words = int(packet.get("min_words") or 0)
    if min_words > 0:
        actual_words = len(candidate_text.split())
        if actual_words < min_words:
            issues.append(
                f"Prose condensation violation: candidate has {actual_words} words, below the {min_words}-word expansion floor."
            )

    # Reassemble full text preserving frozen prefix and suffix byte-for-byte.
    src = packet["full_text"]
    slot = packet["editable_slot"]
    assembled = src[: slot["start"]] + candidate_text + src[slot["end"] :]
    if hashlib.sha256(assembled[: slot["start"]].encode("utf-8")).hexdigest() != packet["prefix_sha256"]:
        issues.append("Frozen prefix hash mismatch.")
    if hashlib.sha256(assembled[slot["start"] + len(candidate_text) :].encode("utf-8")).hexdigest() != packet["suffix_sha256"]:
        issues.append("Frozen Roger suffix hash mismatch.")

    return {
        "valid": not issues,
        "issues": issues,
        "assembled_text": assembled,
        "candidate_sha256": hashlib.sha256(candidate_text.encode("utf-8")).hexdigest(),
    }
