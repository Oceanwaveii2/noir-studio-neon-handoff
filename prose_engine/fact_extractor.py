"""Pass 2-3 Typed Claim Extractor, Timeline Proposal Queuer, and Diff Report Builder."""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Callable, Dict, List, Optional, Sequence

from story_graph.canon_models import CandidateClaim, StoryCoord, ValidationFinding
from story_graph.state_compiler import StateCompiler, list_proposals, propose_canon_change
from story_graph.state_validator import validate_claims

from .canon_classifier import ClassifiedSpan, classify_blocks

_SPOUSE_NO_HUSBAND_RE = re.compile(
    r"\b(?:(?:Francine|Rainee|Stella)['’]s\s+husband|Stan\s+(?:married|was\s+(?:Francine|her)['’]?s?\s+husband)|husband\s+Stan)\b",
    re.IGNORECASE,
)
_JEFF_HUSBAND_RE = re.compile(
    r"\b(?:husband\s+Jeff|Jeff\s+is\s+(?:her|Haley['’]s)\s+husband|Haley['’]s\s+husband(?:\s+Jeff)?|"
    r"(?:Haley\s+)?married\s+to\s+Jeff|your\s+husband\s+Jeff)\b",
    re.IGNORECASE,
)
_JEFF_BOYFRIEND_RE = re.compile(
    r"\b(?:boyfriend\s+Jeff|Jeff\s+is\s+(?:her|Haley['’]s)\s+boyfriend|Haley['’]s\s+boyfriend)\b",
    re.IGNORECASE,
)
_FATHER_RE = re.compile(
    r"\b(?P<subj>Haley|Stella)['’]s\s+(?:biological\s+)?(?:father|dad|daddy|paternal\s+parent)\b"
    r"|\b(?:father|dad|daddy)\s+of\s+(?P<subj2>Haley|Stella)\b"
    r"|\b(?P<subj3>Haley|Stella)\s+(?:has|had|met|visited|called)\s+(?:a\s+|her\s+)?(?:biological\s+)?(?:father|dad|daddy)\b",
    re.IGNORECASE,
)
_HALEY_FOX_TRAIT_RE = re.compile(
    r"\bHaley\b[^.!?\n]{0,70}\b(?:shapeshifts?|morphs?|transformed?|flicks?\s+her\s+tail|fox\s+tail|pointed\s+ears|fox\s+ears|fox\s+fur)\b",
    re.IGNORECASE,
)
_FOX_SON_RE = re.compile(
    r"\b(?P<subj>Rainee|Stella|Noir|fox\w*|siren\w*)[^.!?\n]{0,60}\b(?:gave\s+birth\s+to|bore|had)\s+(?:a\s+)?(?:son|boy|male\s+child)\b",
    re.IGNORECASE,
)
_ATTRACTION_JEFF_RE = re.compile(
    r"\bHaley\b[^.!?\n]{0,70}\b(?:eagerly\s+kissed|lusts?\s+after|magnetically\s+drawn\s+to|eagerly\s+sleeps?\s+with)\s+Jeff\b",
    re.IGNORECASE,
)
_FOX_MALE_DATING_RE = re.compile(
    r"\b(?P<subj>Rainee|Stella|Noir)\b[^.!?\n]{0,60}\b(?:dated|kissed|seduced|dated\s+a\s+guy|went\s+out\s+with)\b[^.!?\n]{0,40}\b(?:man|guy|boyfriend|him)\b",
    re.IGNORECASE,
)
_JESS_DEVICE_RE = re.compile(
    r"\bJeff\b[^.!?\n]{0,90}\b(?:turn(?:s|ed|ing)?\s+into|transform(?:s|ed|ing)?\s+into|becomes?)\s+Jess\b"
    r"|\bdevice\b[^.!?\n]{0,80}\bJess\b",
    re.IGNORECASE,
)
_HOLLY_AFFAIR_RE = re.compile(
    r"\bHaley\b[^.!?\n]{0,80}\b(?:cheats?|cheated|cheating|affair|entangled)\b[^.!?\n]{0,80}\bHolly(?:\s+Graham)?\b",
    re.IGNORECASE,
)


def extract_claims(
    spans: Sequence[ClassifiedSpan],
    coord: StoryCoord,
    state_guards: Sequence[Any] = (),
    *,
    extractor_fn: Optional[Callable[[ClassifiedSpan, StoryCoord], Sequence[CandidateClaim]]] = None,
) -> List[CandidateClaim]:
    """Extract typed CandidateClaim objects from classified sentence spans."""
    claims: List[CandidateClaim] = []
    idx = 0

    def add(
        span: ClassifiedSpan,
        m_start: int,
        m_end: int,
        subj: str,
        pred: str,
        val: str,
        *,
        suggested_delta: Optional[Dict[str, Any]] = None,
    ) -> None:
        nonlocal idx
        idx += 1
        claims.append(
            CandidateClaim(
                claim_id=f"ext-{idx}",
                coord=coord,
                block_id=span.block_id,
                span_start=span.span_start + m_start,
                span_end=span.span_start + m_end,
                excerpt=span.excerpt,
                assertion_class=span.assertion_class,
                subject_id=subj,
                predicate=pred,
                value_or_target=val,
                speaker_id=span.speaker_id,
                source_origin=span.source_origin,
                suggested_delta=suggested_delta,
            )
        )

    for span in spans:
        text = span.excerpt
        for law in state_guards:
            if not getattr(law, "pattern", None):
                continue
            for m in re.finditer(law.pattern, text, flags=re.IGNORECASE):
                add(span, m.start(), m.end(), "ling", "import_bleed", m.group(0))

        for m in _SPOUSE_NO_HUSBAND_RE.finditer(text):
            add(span, m.start(), m.end(), "francine", "spouse_role", "husband")

        for m in _JEFF_HUSBAND_RE.finditer(text):
            add(span, m.start(), m.end(), "haley", "relationship_label", "husband")

        for m in _JEFF_BOYFRIEND_RE.finditer(text):
            add(span, m.start(), m.end(), "haley", "relationship_label", "boyfriend")

        for m in _FATHER_RE.finditer(text):
            after = text[m.end():m.end() + 20]
            if re.match(r"(?:-in-law\b|\s+figure\b)", after, re.IGNORECASE):
                continue
            subj = (m.group("subj") or m.group("subj2") or m.group("subj3") or "haley").casefold()
            add(span, m.start(), m.end(), subj, "biological_father", "male")

        for m in _HALEY_FOX_TRAIT_RE.finditer(text):
            add(span, m.start(), m.end(), "haley", "fox_trait_manifestation", "fox")

        for m in _FOX_SON_RE.finditer(text):
            subj = (m.group("subj") or "rainee").casefold()
            add(span, m.start(), m.end(), subj, "biological_son", "son")

        for m in _ATTRACTION_JEFF_RE.finditer(text):
            add(span, m.start(), m.end(), "haley", "romantic_attraction", "jeff")

        for m in _FOX_MALE_DATING_RE.finditer(text):
            subj = m.group("subj").casefold()
            add(span, m.start(), m.end(), subj, "male_attraction", "man")

        for m in _JESS_DEVICE_RE.finditer(text):
            add(
                span,
                m.start(),
                m.end(),
                "jeff",
                "intimacy_as_jess",
                "jess",
                suggested_delta={
                    "kind": "state_delta",
                    "op": "GRANT_DEVICE",
                    "subject_id": "jeff",
                    "payload": {
                        "device_id": "jess_intimacy_device",
                        "transforms_to": "jess",
                        "context": "intimacy_and_marriage_salvage",
                    },
                    "rationale": f"Text depicts Jeff transforming to Jess: '{span.excerpt[:120]}'",
                },
            )

        for m in _HOLLY_AFFAIR_RE.finditer(text):
            add(
                span,
                m.start(),
                m.end(),
                "haley",
                "romantic_attraction",
                "holly_graham",
                suggested_delta={
                    "kind": "state_delta",
                    "op": "SET_RELATIONSHIP",
                    "subject_id": "haley",
                    "target_id": "holly_graham",
                    "payload": {"status": "affair_cheating", "concurrent_with_marriage": True},
                    "rationale": f"Text depicts Haley's affair with Holly Graham: '{span.excerpt[:120]}'",
                },
            )

        if extractor_fn is not None:
            for extra in extractor_fn(span, coord):
                claims.append(extra)

    return claims


def _should_queue_delta(delta_spec: Dict[str, Any], state) -> bool:
    op = delta_spec.get("op")
    if op == "GRANT_DEVICE":
        device_id = delta_spec.get("payload", {}).get("device_id")
        return device_id not in state.characters.get(delta_spec["subject_id"], {}).get("devices", {})
    if op == "SET_RELATIONSHIP":
        key = (delta_spec["subject_id"], delta_spec.get("target_id", ""))
        existing = state.relationships.get(key)
        return not existing or existing.get("status") != delta_spec.get("payload", {}).get("status")
    return True


def run_canon_passes(
    blocks_or_text: Sequence[dict] | str,
    coord: StoryCoord,
    conn: sqlite3.Connection,
    *,
    viewpoint: Optional[str] = None,
    source_origin: str = "author_manuscript",
    queue_proposals: bool = False,
    extractor_fn: Optional[Callable[[ClassifiedSpan, StoryCoord], Sequence[CandidateClaim]]] = None,
) -> Dict[str, Any]:
    """Execute Pass 0-3 over manuscript blocks/text against compiled state at coord."""
    state = StateCompiler(conn).compile_state(coord, viewpoint=viewpoint)
    spans = classify_blocks(blocks_or_text, source_origin=source_origin)
    claims = extract_claims(spans, coord, state.import_bleed_guards, extractor_fn=extractor_fn)
    findings: List[ValidationFinding] = validate_claims(claims, state)

    queued: List[str] = []
    if queue_proposals:
        existing_pending = {
            (p["episode_id"], p["kind"], p["payload"].get("op"), p["payload"].get("subject_id"), p["payload"].get("target_id"))
            for p in list_proposals(conn, coord.universe_id, status="pending")
        }
        for claim in claims:
            if not claim.suggested_delta:
                continue
            spec = claim.suggested_delta
            if not _should_queue_delta(spec, state):
                continue
            sig = (coord.episode_id, spec["kind"], spec.get("op"), spec.get("subject_id"), spec.get("target_id"))
            if sig in existing_pending:
                continue
            pid = propose_canon_change(
                conn,
                coord,
                kind=spec["kind"],
                payload={
                    "op": spec["op"],
                    "subject_id": spec["subject_id"],
                    "target_id": spec.get("target_id"),
                    "payload": spec.get("payload", {}),
                },
                rationale=spec.get("rationale", "Extracted from manuscript"),
            )
            queued.append(pid)
            existing_pending.add(sig)

    by_status = {
        key: [f.to_dict() for f in findings if f.status == key]
        for key in ("conflict", "warning", "advisory", "uncertain", "supported")
    }
    return {
        "coord": coord.to_dict(),
        "state_digest": state.state_digest,
        "spans_count": len(spans),
        "claims": [c.to_dict() for c in claims],
        "findings": [f.to_dict() for f in findings],
        "conflicts": by_status["conflict"],
        "warnings": by_status["warning"],
        "advisories": by_status["advisory"],
        "uncertain": by_status["uncertain"],
        "supported": by_status["supported"],
        "queued_proposals": queued,
    }
