"""Deterministic canon auto-correction backed by world laws, character profiles, and compiled minds."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_graph.seeds.afm_seed import DEFAULT_AFM_UNIVERSE

from .canon_guard import compile_afm_state
from .canon_rules import DEFAULT_NEGATION_CUES, sentence_window

_META_CONTEXT_RE = re.compile(
    r"\b(?:source\s+show|american\s+dad|broadcast|cartoon|tv\s+show|cosplay\w*|myth|rumou?r)\b",
    re.IGNORECASE,
)
_EXTRA_NEGATIONS = ("no husband", "not her husband", "not a husband", "not married", "wasn't", "isn't", "weren't")


@dataclass(frozen=True)
class CanonCorrection:
    """One deterministic span replacement derived from active world rules, profiles, or minds."""

    start: int
    end: int
    original: str
    replacement: str
    rule_id: str
    code: str
    source: str
    reason: str
    confidence: str = "deterministic"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonCorrectionResult:
    """Outcome of flagging and automatically repairing canon conflicts in prose."""

    original_text: str
    corrected_text: str
    applied_count: int
    corrections: Tuple[CanonCorrection, ...]
    remaining_violations: Tuple[Dict[str, Any], ...]
    advisories: Tuple[Dict[str, Any], ...]
    coord: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_text": self.original_text,
            "corrected_text": self.corrected_text,
            "applied_count": self.applied_count,
            "corrections": [c.to_dict() for c in self.corrections],
            "remaining_violations": list(self.remaining_violations),
            "advisories": list(self.advisories),
            "coord": dict(self.coord),
        }


def _match_case(sample: str, target: str) -> str:
    """Preserve ALL CAPS, Title Case, or lowercase casing from the matched phrase."""
    letters = [ch for ch in sample if ch.isalpha()]
    if letters and all(ch.isupper() for ch in letters):
        return target.upper()
    if letters and all(ch.islower() for ch in letters):
        return target.lower()
    sample_words = re.findall(r"[A-Za-z']+", sample)
    target_words = target.split(" ")
    if len(sample_words) == len(target_words) and all(sw[:1].isupper() for sw in sample_words):
        return " ".join(tw[:1].upper() + tw[1:] for tw in target_words)
    if sample[:1].isupper() and not target[:1].isupper():
        return target[:1].upper() + target[1:]
    return target


def _is_protected(start: int, end: int, protected_ranges: Sequence[Tuple[int, int]]) -> bool:
    for a, b in protected_ranges or ():
        if start < b and a < end:
            return True
    return False


def _is_exempt_sentence(text: str, start: int, end: int, *, respect_teasing: bool = False) -> bool:
    sentence = sentence_window(text, start, end)
    lowered = sentence.casefold()
    if any(cue in lowered for cue in DEFAULT_NEGATION_CUES + _EXTRA_NEGATIONS):
        return True
    if _META_CONTEXT_RE.search(sentence):
        return True
    if respect_teasing and re.search(r"\b(?:jok\w*|just\s+kidding|teas\w*|sarcas\w*)\b", sentence, re.I):
        return True
    return False


def _add_regex_repairs(
    candidates: List[CanonCorrection],
    text: str,
    pattern: re.Pattern[str],
    replacement_fn,
    *,
    rule_id: str,
    code: str,
    source: str,
    reason: str,
    protected_ranges: Sequence[Tuple[int, int]] = (),
    respect_teasing: bool = False,
) -> None:
    for m in pattern.finditer(text):
        start, end = m.span()
        if _is_protected(start, end, protected_ranges):
            continue
        if _is_exempt_sentence(text, start, end, respect_teasing=respect_teasing):
            continue
        rep = replacement_fn(m)
        if not rep or rep == m.group(0):
            continue
        candidates.append(
            CanonCorrection(
                start=start,
                end=end,
                original=m.group(0),
                replacement=rep,
                rule_id=rule_id,
                code=code,
                source=source,
                reason=reason,
            )
        )


def _mind_surname_repairs(
    text: str,
    compiled_state,
    character_profiles: Optional[dict],
    protected_ranges: Sequence[Tuple[int, int]],
) -> List[CanonCorrection]:
    """Repair wrong source-show surname ('Smith') to authoritative household surname ('Ling') from CharacterMinds."""
    candidates: List[CanonCorrection] = []
    ling_names = []
    for mind in (compiled_state.characters or {}).values():
        surname = mind.get("default_surname", "") if isinstance(mind, dict) else getattr(mind, "default_surname", "")
        cname = mind.get("canonical_name", "") if isinstance(mind, dict) else getattr(mind, "canonical_name", "")
        if str(surname).casefold() == "ling" and str(cname).strip():
            ling_names.append(str(cname).strip().split()[0])
    has_import_guard = any(
        getattr(law, "law_id", None) == "import_guard_smith_stan"
        or (isinstance(law, dict) and law.get("law_id") == "import_guard_smith_stan")
        for law in getattr(compiled_state, "import_bleed_guards", ()) or ()
    )
    if not ling_names and not has_import_guard and not (
        isinstance(character_profiles, dict) and any("ling" in str(v).casefold() for v in character_profiles.values())
    ):
        return candidates

    first_alternation = "|".join(sorted({re.escape(n) for n in ling_names}, key=len, reverse=True))
    if first_alternation:
        _add_regex_repairs(
            candidates,
            text,
            re.compile(rf"\b({first_alternation})\s+Smith\b", re.IGNORECASE),
            lambda m: _match_case(m.group(0), f"{m.group(1)} Ling"),
            rule_id="ling_surname_invariant",
            code="SHOW_IMPORT_BLEED",
            source="character_minds:surname",
            reason="Character minds belong to the Ling household, never Smith.",
            protected_ranges=protected_ranges,
        )

    _add_regex_repairs(
        candidates,
        text,
        re.compile(r"\bSmith\s+(Kitchen|house|household|residence|family|living\s+room|driveway|hallway|home)\b", re.IGNORECASE),
        lambda m: _match_case(m.group(0), f"Ling {m.group(1)}"),
        rule_id="ling_surname_invariant",
        code="SHOW_IMPORT_BLEED",
        source="character_minds:home_location",
        reason="Household location belongs to the Ling home, not Smith.",
        protected_ranges=protected_ranges,
    )
    _add_regex_repairs(
        candidates,
        text,
        re.compile(r"\bthe\s+Smiths\b", re.IGNORECASE),
        lambda m: _match_case(m.group(0), "the Lings"),
        rule_id="ling_surname_invariant",
        code="SHOW_IMPORT_BLEED",
        source="character_minds:family",
        reason="The family name is Ling (the Lings), never the Smiths.",
        protected_ranges=protected_ranges,
    )
    _add_regex_repairs(
        candidates,
        text,
        re.compile(r"\bMrs\.?\s+Smith\b", re.IGNORECASE),
        lambda m: _match_case(m.group(0), "Francine Ling"),
        rule_id="ling_surname_invariant",
        code="SHOW_IMPORT_BLEED",
        source="character_minds:francine",
        reason="Francine never married Stan and kept Francine Ling.",
        protected_ranges=protected_ranges,
    )
    return candidates


def _relationship_repairs(
    text: str,
    compiled_state,
    protected_ranges: Sequence[Tuple[int, int]],
) -> List[CanonCorrection]:
    """Repair epoch-anachronistic relationship labels and impossible co-parent/spouse nouns."""
    candidates: List[CanonCorrection] = []
    hj_rel = compiled_state.relationships.get(("haley", "jeff")) or compiled_state.relationships.get(("jeff", "haley"))
    if hj_rel and hj_rel.get("status") == "dating":
        _add_regex_repairs(
            candidates,
            text,
            re.compile(r"\b(husband)(\s+Jeff(?:'s|’s)?)\b", re.IGNORECASE),
            lambda m: _match_case(m.group(1), "boyfriend") + m.group(2),
            rule_id="haley_jeff_spring_break_dating",
            code="ERA_ANACHRONISM",
            source="relationships:haley->jeff",
            reason="At Spring Break-Up, Haley and Jeff are dating (boyfriend), not yet married.",
            protected_ranges=protected_ranges,
        )
        _add_regex_repairs(
            candidates,
            text,
            re.compile(r"\b(Haley(?:'s|’s)\s+)(husband)\b", re.IGNORECASE),
            lambda m: m.group(1) + _match_case(m.group(2), "boyfriend"),
            rule_id="haley_jeff_spring_break_dating",
            code="ERA_ANACHRONISM",
            source="relationships:haley->jeff",
            reason="At Spring Break-Up, Jeff is Haley's boyfriend, not husband.",
            protected_ranges=protected_ranges,
        )
        _add_regex_repairs(
            candidates,
            text,
            re.compile(r"\bmarried\s+to\s+Jeff\b", re.IGNORECASE),
            lambda m: _match_case(m.group(0), "dating Jeff"),
            rule_id="haley_jeff_spring_break_dating",
            code="ERA_ANACHRONISM",
            source="relationships:haley->jeff",
            reason="At Spring Break-Up, Haley is dating Jeff (not married yet).",
            protected_ranges=protected_ranges,
        )

    fr_rel = compiled_state.relationships.get(("francine", "rainee")) or compiled_state.relationships.get(("rainee", "francine"))
    if fr_rel and ("married" in str(fr_rel.get("status", "")) or "wife" in (fr_rel.get("allowed_terms") or ())):
        _add_regex_repairs(
            candidates,
            text,
            re.compile(r"\b((?:Francine|Rainee)(?:'s|’s)\s+)(husband)\b", re.IGNORECASE),
            lambda m: m.group(1) + _match_case(m.group(2), "wife"),
            rule_id="ling_no_husband",
            code="LING_MARRIAGE_CONFLICT",
            source="relationships:francine<->rainee",
            reason="Francine Ling and Rainee Ling are married to each other, not to any husband.",
            protected_ranges=protected_ranges,
        )
    return candidates


def _merge_non_overlapping(candidates: Sequence[CanonCorrection]) -> List[CanonCorrection]:
    chosen: List[CanonCorrection] = []
    last_end = -1
    for item in sorted(candidates, key=lambda c: (c.start, -(c.end - c.start))):
        if item.start < last_end:
            continue
        chosen.append(item)
        last_end = item.end
    return chosen


def plan_canon_corrections(
    text: str,
    *,
    compiled_state=None,
    character_profiles: Optional[dict] = None,
    episode_id: str = "spring-break",
    branch: str = "main",
    beat: int = 0,
    viewpoint: Optional[str] = None,
    universe_id: str = DEFAULT_AFM_UNIVERSE,
    timeline_conn=None,
    protected_ranges: Sequence[Tuple[int, int]] = (),
) -> List[CanonCorrection]:
    """Build deterministic canon corrections from compiled world state, minds, profiles, and laws."""
    state = compiled_state or compile_afm_state(
        universe_id=universe_id,
        branch=branch,
        episode_id=episode_id,
        beat=beat,
        viewpoint=viewpoint,
        timeline_conn=timeline_conn,
    )
    raw: List[CanonCorrection] = []
    raw.extend(_mind_surname_repairs(text, state, character_profiles, protected_ranges))
    raw.extend(_relationship_repairs(text, state, protected_ranges))
    return _merge_non_overlapping(raw)


def auto_correct_canon(
    text: str,
    *,
    apply: bool = True,
    compiled_state=None,
    world_state=None,
    character_profiles: Optional[dict] = None,
    episode_id: str = "spring-break",
    branch: str = "main",
    beat: int = 0,
    viewpoint: Optional[str] = None,
    universe_id: str = DEFAULT_AFM_UNIVERSE,
    timeline_conn=None,
    protected_ranges: Sequence[Tuple[int, int]] = (),
) -> CanonCorrectionResult:
    """Flag and automatically correct canon violations backed by world rules, profiles, and minds."""
    from story_graph.state_validator import validate_text

    state = compiled_state or compile_afm_state(
        universe_id=universe_id,
        branch=branch,
        episode_id=episode_id,
        beat=beat,
        viewpoint=viewpoint,
        timeline_conn=timeline_conn,
    )
    planned = plan_canon_corrections(
        text,
        compiled_state=state,
        character_profiles=character_profiles,
        episode_id=episode_id,
        branch=branch,
        beat=beat,
        viewpoint=viewpoint,
        universe_id=universe_id,
        timeline_conn=timeline_conn,
        protected_ranges=protected_ranges,
    )
    updated = text
    applied_count = 0
    if apply and planned:
        for fix in sorted(planned, key=lambda c: -c.start):
            updated = updated[: fix.start] + fix.replacement + updated[fix.end :]
            applied_count += 1

    post_findings = validate_text(updated, state)
    remaining = [f.to_dict() for f in post_findings if f.status == "conflict"]
    advisories = [f.to_dict() for f in post_findings if f.status != "conflict"]
    if world_state is not None:
        existing_evidence = {str(item.get("evidence") or "").casefold() for item in remaining}
        for matched, why in world_state.violations(updated):
            if matched.casefold() not in existing_evidence:
                remaining.append(
                    {
                        "status": "conflict",
                        "severity": "error",
                        "code": "WORLD_STATE_RULE",
                        "rule_id": "world_state",
                        "reason": why,
                        "evidence": matched,
                    }
                )
    return CanonCorrectionResult(
        original_text=text,
        corrected_text=updated,
        applied_count=applied_count,
        corrections=tuple(planned),
        remaining_violations=tuple(remaining),
        advisories=tuple(advisories),
        coord=state.coord.to_dict(),
    )
