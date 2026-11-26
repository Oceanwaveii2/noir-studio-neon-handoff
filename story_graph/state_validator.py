"""Deterministic validation of structured claims and classified text against CompiledWorldState."""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple

from .canon_models import (
    ASSERTION_CLASSES,
    CandidateClaim,
    CompiledWorldState,
    ValidationFinding,
)

_SENTENCE_SPLIT = re.compile(r"[^.!?\n]+(?:[.!?]+|\n|$)")
_NEGATION_RE = re.compile(
    r"\b(?:never|no|not|neither|nor|none|wasn['’]t|weren['’]t|didn['’]t|doesn['’]t|"
    r"don['’]t|isn['’]t|aren['’]t|cannot|can['’]t|never\s+married|kept\s+the\s+ling\s+name|"
    r"instead\s+of|rather\s+than|before\s+(?:the\s+)?wedding|dumped|ex-)\b",
    re.IGNORECASE,
)
_BELIEF_OR_QUOTE_RE = re.compile(
    r"\b(?:believ\w*|thought|thinks?|assumed|imagined|wondered|rumou?r|pretend\w*|"
    r"said|says|claimed|alleged|insisted|knew|source\s+show|american\s+dad|broadcast|cartoon|cosplay\w*)\b",
    re.IGNORECASE,
)
_TEASE_RE = re.compile(r"\b(?:jok\w*|teas\w*|kidding|sarcas\w*)\b", re.IGNORECASE)

_SPOUSE_NO_HUSBAND_RE = re.compile(
    r"\b(?:(?:Francine|Rainee|Stella)['’]s\s+husband|Stan\s+(?:married|was\s+(?:Francine|her)['’]?s?\s+husband)|"
    r"husband\s+Stan)\b",
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
    r"\bHaley['’]s\s+(?:biological\s+)?(?:father|dad|daddy|paternal\s+parent)\b"
    r"|\b(?:father|dad|daddy)\s+of\s+Haley\b"
    r"|\bHaley\s+(?:has|had|met|visited|called)\s+(?:a\s+|her\s+)?(?:biological\s+)?(?:father|dad|daddy)\b",
    re.IGNORECASE,
)
_HALEY_FOX_TRAIT_RE = re.compile(
    r"\bHaley\b[^.!?\n]{0,70}\b(?:shapeshifts?|morphs?|transformed?|flicks?\s+her\s+tail|fox\s+tail|pointed\s+ears|fox\s+ears|fox\s+fur)\b",
    re.IGNORECASE,
)
_FOX_SON_RE = re.compile(
    r"\b(?:Rainee|Stella|Noir|fox\w*|siren\w*)[^.!?\n]{0,60}\b(?:gave\s+birth\s+to|bore|had)\s+(?:a\s+)?(?:son|boy|male\s+child)\b",
    re.IGNORECASE,
)
_ATTRACTION_RE = re.compile(
    r"\bHaley\b[^.!?\n]{0,70}\b(?:eagerly\s+kissed|lusts?\s+after|magnetically\s+drawn\s+to|eagerly\s+sleeps?\s+with)\s+Jeff\b",
    re.IGNORECASE,
)


def _sentence_bounds(text: str, pos: int) -> Tuple[int, int, str]:
    start = max(text.rfind(ch, 0, pos) for ch in ".!?\n") + 1
    ends = [text.find(ch, pos) for ch in ".!?\n"]
    pos_ends = [e + 1 for e in ends if e >= 0]
    end = min(pos_ends) if pos_ends else len(text)
    while end < len(text) and text[end] in "\"'”’)":
        end += 1
    return start, end, text[start:end]


def _law_accepts_assertion(scope: Tuple[str, ...], assertion_class: str) -> bool:
    return assertion_class in scope


def _match_relationship(state: CompiledWorldState, subj: str, target: str) -> Optional[dict]:
    s, t = subj.casefold(), target.casefold()
    return state.relationships.get((s, t)) or state.relationships.get((t, s))


def _check_claim_relationship(claim: CandidateClaim, state: CompiledWorldState) -> List[ValidationFinding]:
    findings: List[ValidationFinding] = []
    subj = claim.subject_id.casefold()
    val = claim.value_or_target.casefold()
    rel = _match_relationship(state, subj, "jeff" if subj == "haley" else val)

    if claim.assertion_class in ("dialogue_teasing", "character_belief", "negated_divergence"):
        if claim.assertion_class == "dialogue_teasing":
            findings.append(
                ValidationFinding(
                    status="advisory",
                    severity="info",
                    code="TEASING_DIALOGUE_EXEMPT",
                    rule_id="speech_act_teasing",
                    reason="Marked as character dialogue teasing/banter; exempt from timeline relationship block.",
                    evidence=claim.excerpt,
                    assertion_class=claim.assertion_class,
                    subject_id=subj,
                    span_start=claim.span_start,
                    span_end=claim.span_end,
                )
            )
        return findings

    if subj in ("francine", "rainee") and claim.predicate == "spouse_role" and "husband" in val:
        return [
            ValidationFinding(
                status="conflict",
                severity="error",
                code="LING_MARRIAGE_CONFLICT",
                rule_id="ling_no_husband",
                reason="Francine Ling and Rainee Ling are married to each other and never married Stan or any husband.",
                evidence=claim.excerpt,
                assertion_class=claim.assertion_class,
                subject_id=subj,
                span_start=claim.span_start,
                span_end=claim.span_end,
                provenance="character_minds:francine",
                quick_actions=("Rewrite span", "Mark Character Belief", "Mark Negated Divergence"),
            )
        ]

    if subj == "haley" and claim.predicate == "relationship_label":
        term = val.strip()
        edge = _match_relationship(state, "haley", "jeff")
        if edge:
            allowed = {t.casefold() for t in edge.get("allowed_terms", ())}
            anachronistic = {t.casefold() for t in edge.get("anachronistic_terms", ())}
            if term in anachronistic:
                findings.append(
                    ValidationFinding(
                        status="conflict",
                        severity="error",
                        code="ERA_ANACHRONISM",
                        rule_id="haley_jeff_timeline",
                        reason=(
                            f"At {state.coord.episode_id} (pos={state.coord.episode_position}), Haley–Jeff is "
                            f"'{edge['status']}' (allowed: {sorted(allowed)}; anachronistic here: '{term}')."
                        ),
                        evidence=claim.excerpt,
                        assertion_class=claim.assertion_class,
                        subject_id="haley",
                        span_start=claim.span_start,
                        span_end=claim.span_end,
                        provenance=str(edge.get("last_delta_id", "timeline_delta")),
                        quick_actions=("Rewrite to boyfriend", "Tag as Dialogue Tease", "Propose Timeline Delta"),
                    )
                )
            elif term in allowed or edge.get("status") == term:
                findings.append(
                    ValidationFinding(
                        status="supported",
                        severity="info",
                        code="ERA_RELATIONSHIP_VALID",
                        rule_id="haley_jeff_timeline",
                        reason=f"Term '{term}' matches Haley–Jeff relationship '{edge['status']}' at {state.coord.episode_id}.",
                        evidence=claim.excerpt,
                        assertion_class=claim.assertion_class,
                        subject_id="haley",
                        span_start=claim.span_start,
                        span_end=claim.span_end,
                        provenance=str(edge.get("last_delta_id", "timeline_delta")),
                    )
                )

    elif subj == "haley" and claim.predicate == "romantic_attraction":
        char = state.characters.get("haley", {})
        att = char.get("attraction", {})
        repulsed = {r.casefold() for r in att.get("repulsed_by", ())}
        target_cf = val.split(":")[-1].strip()
        if target_cf in repulsed:
            jeff_devices = state.characters.get("jeff", {}).get("devices", {})
            if target_cf == "jeff" and "jess" not in val:
                reason = (
                    "Haley's awakened fox genetics mirror her mothers strongly, leaving her physically repulsed by Jeff."
                )
                if "jess_intimacy_device" in jeff_devices:
                    reason += " Intimacy is salvaged only when Jeff transforms into Jess."
                findings.append(
                    ValidationFinding(
                        status="conflict",
                        severity="error",
                        code="CHARACTER_STATE_CONFLICT",
                        rule_id="haley_attraction_profile",
                        reason=reason,
                        evidence=claim.excerpt,
                        assertion_class=claim.assertion_class,
                        subject_id="haley",
                        span_start=claim.span_start,
                        span_end=claim.span_end,
                        provenance=f"biology:{char.get('biology_stage')}",
                        quick_actions=("Route via Jess device", "Mark Character Belief", "Rewrite span"),
                    )
                )
        elif target_cf in {x.casefold() for x in att.get("attracted_to", ())} or "jess" in val:
            findings.append(
                ValidationFinding(
                    status="supported",
                    severity="info",
                    code="ATTRACTION_SUPPORTED",
                    rule_id="haley_attraction_profile",
                    reason=f"Attraction to '{val}' aligns with Haley's compiled state at {state.coord.episode_id}.",
                    evidence=claim.excerpt,
                    assertion_class=claim.assertion_class,
                    subject_id="haley",
                    span_start=claim.span_start,
                    span_end=claim.span_end,
                )
            )
    return findings


def validate_claims(
    claims: Sequence[CandidateClaim],
    state: CompiledWorldState,
) -> List[ValidationFinding]:
    """Validate structured candidate claims against a compiled world & character state."""
    findings: List[ValidationFinding] = []
    for claim in claims:
        if claim.assertion_class not in ASSERTION_CLASSES:
            raise ValueError(f"Unsupported assertion class: {claim.assertion_class}")
        subj = claim.subject_id.casefold()
        pred = claim.predicate.casefold()
        val = claim.value_or_target.casefold()
        char = state.characters.get(subj, {})

        # 1. Hard Biological Invariants
        if pred == "biological_son" and claim.assertion_class in ("narration_fact", "stage_direction", "dialogue_literal_claim"):
            findings.append(
                ValidationFinding(
                    status="conflict",
                    severity="error",
                    code="BIOLOGY_INVARIANT_BREACH",
                    rule_id="fox_no_sons",
                    reason="Hard biological world law: alien fox lineages cannot have biological sons.",
                    evidence=claim.excerpt,
                    assertion_class=claim.assertion_class,
                    subject_id=subj,
                    span_start=claim.span_start,
                    span_end=claim.span_end,
                    quick_actions=("Rewrite span", "Mark Character Belief"),
                )
            )
            continue

        if pred == "siren_pheromone" and val == "male" and claim.assertion_class in (
            "narration_fact", "stage_direction", "dialogue_literal_claim"
        ):
            findings.append(
                ValidationFinding(
                    status="conflict",
                    severity="error",
                    code="BIOLOGY_INVARIANT_BREACH",
                    rule_id="fox_female_siren_pheromones",
                    reason="Hard biological world law: siren pheromones exist only in female fox lineages.",
                    evidence=claim.excerpt,
                    assertion_class=claim.assertion_class,
                    subject_id=subj,
                    span_start=claim.span_start,
                    span_end=claim.span_end,
                )
            )
            continue

        if pred == "biological_father" and subj in ("haley", "stella"):
            if claim.assertion_class in ("narration_fact", "stage_direction", "dialogue_literal_claim"):
                findings.append(
                    ValidationFinding(
                        status="conflict",
                        severity="error",
                        code="PARENTAGE_INVARIANT_BREACH",
                        rule_id="two_mom_nanomachinery",
                        reason=f"{subj.title()} was born to Francine and Rainee via genetic nanomachinery with no biological father.",
                        evidence=claim.excerpt,
                        assertion_class=claim.assertion_class,
                        subject_id=subj,
                        span_start=claim.span_start,
                        span_end=claim.span_end,
                    )
                )
            elif claim.assertion_class == "character_belief":
                findings.append(
                    ValidationFinding(
                        status="uncertain",
                        severity="info",
                        code="CHARACTER_BELIEF_UNCERTAIN",
                        rule_id="two_mom_nanomachinery",
                        reason="Parentage mention appears inside character belief/rumor framing, not an objective narration fact.",
                        evidence=claim.excerpt,
                        assertion_class=claim.assertion_class,
                        subject_id=subj,
                        span_start=claim.span_start,
                        span_end=claim.span_end,
                    )
                )
            continue

        # 2. Soft Biological Tendency with Rare Character Exception (e.g., Noir)
        if pred == "male_attraction":
            if char.get("biology_stage") == "dormant_hybrid":
                findings.append(
                    ValidationFinding(
                        status="supported",
                        severity="info",
                        code="DORMANT_HYBRID_BASELINE",
                        rule_id="fox_sapphic_tendency",
                        reason=f"{subj.title()} has dormant fox genes at {state.coord.episode_id}; human male attraction is valid.",
                        evidence=claim.excerpt,
                        assertion_class=claim.assertion_class,
                        subject_id=subj,
                        span_start=claim.span_start,
                        span_end=claim.span_end,
                    )
                )
                continue
            exc = char.get("exceptions", {}).get("fox_sapphic_tendency")
            if exc:
                findings.append(
                    ValidationFinding(
                        status="supported",
                        severity="info",
                        code="SOFT_LAW_EXCEPTION_GRANTED",
                        rule_id="fox_sapphic_tendency",
                        reason=f"Rare male-attraction exception authorized by character trait '{exc['trait_id']}'.",
                        evidence=claim.excerpt,
                        assertion_class=claim.assertion_class,
                        subject_id=subj,
                        span_start=claim.span_start,
                        span_end=claim.span_end,
                        provenance=f"character_trait:{exc['trait_id']}",
                    )
                )
                continue
            if claim.assertion_class in ("narration_fact", "stage_direction", "dialogue_literal_claim"):
                findings.append(
                    ValidationFinding(
                        status="warning",
                        severity="warning",
                        code="SOFT_TENDENCY_UNEXPLAINED",
                        rule_id="fox_sapphic_tendency",
                        reason=(
                            f"Fox attraction to men is rare without an explicit character exception trait for '{subj}'."
                        ),
                        evidence=claim.excerpt,
                        assertion_class=claim.assertion_class,
                        subject_id=subj,
                        span_start=claim.span_start,
                        span_end=claim.span_end,
                        quick_actions=("Grant Character Trait Exception", "Tag as Dialogue Tease", "Rewrite span"),
                    )
                )
            continue

        # 3. Fox Biology / Transformation Manifestation
        if pred == "fox_trait_manifestation":
            if not char.get("can_self_morph") and char.get("biology_stage") in ("baseline", "dormant_hybrid"):
                if claim.assertion_class in ("narration_fact", "stage_direction", "dialogue_literal_claim"):
                    findings.append(
                        ValidationFinding(
                            status="conflict",
                            severity="error",
                            code="BIOLOGY_ANACHRONISM",
                            rule_id="dormant_fox_awakening",
                            reason=f"At {state.coord.episode_id}, {subj.title()} is still '{char.get('biology_stage')}' and has not awakened fox traits.",
                            evidence=claim.excerpt,
                            assertion_class=claim.assertion_class,
                            subject_id=subj,
                            span_start=claim.span_start,
                            span_end=claim.span_end,
                            quick_actions=("Rewrite span", "Propose Timeline Delta"),
                        )
                    )
            else:
                findings.append(
                    ValidationFinding(
                        status="supported",
                        severity="info",
                        code="AWAKENED_BIOLOGY_VALID",
                        rule_id="dormant_fox_awakening",
                        reason=f"At {state.coord.episode_id}, {subj.title()} is awakened ('{char.get('biology_stage')}').",
                        evidence=claim.excerpt,
                        assertion_class=claim.assertion_class,
                        subject_id=subj,
                        span_start=claim.span_start,
                        span_end=claim.span_end,
                    )
                )
            continue

        # 4. Import Bleed Guards (Smith / Stan)
        if pred == "import_bleed":
            if claim.assertion_class in ("show_quote", "negated_divergence") or claim.source_origin == "broadcast_quote_fixture":
                continue
            findings.append(
                ValidationFinding(
                    status="conflict",
                    severity="error",
                    code="SHOW_IMPORT_BLEED",
                    rule_id="import_guard_smith_stan",
                    reason="American Dad! show-import bleed: household/surname is Ling, not Smith, and Stan never married Francine.",
                    evidence=claim.excerpt,
                    assertion_class=claim.assertion_class,
                    subject_id=subj,
                    span_start=claim.span_start,
                    span_end=claim.span_end,
                    quick_actions=("Replace with Ling", "Mark Broadcast Quote", "Mark Negated Divergence"),
                )
            )
            continue

        # 5. Relationships & Devices
        if pred in ("relationship_label", "spouse_role", "romantic_attraction"):
            findings.extend(_check_claim_relationship(claim, state))
            continue

        if pred == "intimacy_as_jess":
            devices = state.characters.get("jeff", {}).get("devices", {})
            if "jess_intimacy_device" in devices:
                findings.append(
                    ValidationFinding(
                        status="supported",
                        severity="info",
                        code="DEVICE_SALVAGE_SUPPORTED",
                        rule_id="tapped_out_jess_device",
                        reason="Jeff holds the Jess transformation device in this arc.",
                        evidence=claim.excerpt,
                        assertion_class=claim.assertion_class,
                        subject_id="jeff",
                        span_start=claim.span_start,
                        span_end=claim.span_end,
                    )
                )
            else:
                findings.append(
                    ValidationFinding(
                        status="conflict",
                        severity="error",
                        code="DEVICE_ANACHRONISM",
                        rule_id="tapped_out_jess_device",
                        reason=f"At {state.coord.episode_id}, Jeff has not yet acquired the Jess transformation device.",
                        evidence=claim.excerpt,
                        assertion_class=claim.assertion_class,
                        subject_id="jeff",
                        span_start=claim.span_start,
                        span_end=claim.span_end,
                    )
                )
            continue

        # 6. Epistemic / Hidden-Fact Check
        if pred == "knowledge_mention":
            for hidden in state.hidden_facts:
                obj = str(hidden.get("object_value", "")).casefold()
                if obj and len(obj) >= 6 and obj in claim.excerpt.casefold():
                    findings.append(
                        ValidationFinding(
                            status="conflict",
                            severity="error",
                            code="EPISTEMIC_OR_BRANCH_LEAK",
                            rule_id="epistemic_scope",
                            reason=f"References withheld fact ({hidden.get('reason')}): '{hidden.get('object_value')}'.",
                            evidence=claim.excerpt,
                            assertion_class=claim.assertion_class,
                            subject_id=subj,
                            span_start=claim.span_start,
                            span_end=claim.span_end,
                        )
                    )
    return findings


def _is_quoted_span(text: str, s_start: int, match_start: int, match_end: int, s_end: int) -> bool:
    before = text[s_start:match_start]
    after = text[match_end:s_end]
    if before.count('"') % 2 == 1 or ("“" in before and "”" not in before):
        return True
    if ("‘" in before and "’" not in before and "’" in after) or (
        re.search(r"(?:^|\s)'[^'\n]*$", before) and "'" in after
    ):
        return True
    return False


def _classify_sentence(
    sentence: str,
    default_assertion: str,
    source_origin: str,
    *,
    quoted: bool = False,
) -> str:
    if source_origin == "broadcast_quote_fixture":
        return "show_quote"
    if _NEGATION_RE.search(sentence):
        return "negated_divergence"
    if quoted or _BELIEF_OR_QUOTE_RE.search(sentence):
        return "character_belief"
    if _TEASE_RE.search(sentence):
        return "dialogue_teasing"
    return default_assertion


def validate_text(
    text: str,
    state: CompiledWorldState,
    *,
    assertion_default: str = "narration_fact",
    source_origin: str = "author_manuscript",
    block_id: str = "text",
) -> List[ValidationFinding]:
    """Classify and check raw prose against a CompiledWorldState deterministically."""
    if not text:
        return []
    claims: List[CandidateClaim] = []
    idx = 0

    def add(span_start: int, span_end: int, excerpt: str, subj: str, pred: str, val: str, ac: str) -> None:
        nonlocal idx
        idx += 1
        claims.append(
            CandidateClaim(
                claim_id=f"txt-{idx}",
                coord=state.coord,
                block_id=block_id,
                span_start=span_start,
                span_end=span_end,
                excerpt=excerpt,
                assertion_class=ac,
                subject_id=subj,
                predicate=pred,
                value_or_target=val,
                source_origin=source_origin,
            )
        )

    def classify(m: re.Match[str]) -> str:
        s_start, s_end, sent = _sentence_bounds(text, m.start())
        quoted = _is_quoted_span(text, s_start, m.start(), m.end(), s_end)
        return _classify_sentence(sent, assertion_default, source_origin, quoted=quoted)

    for law in state.import_bleed_guards:
        if not law.pattern:
            continue
        for m in re.finditer(law.pattern, text, flags=re.IGNORECASE):
            ac = classify(m)
            if _law_accepts_assertion(law.assertion_scope, ac) or ac in ("show_quote", "negated_divergence"):
                add(m.start(), m.end(), m.group(0), "ling", "import_bleed", m.group(0), ac)

    for m in _SPOUSE_NO_HUSBAND_RE.finditer(text):
        add(m.start(), m.end(), m.group(0), "francine", "spouse_role", "husband", classify(m))

    for m in _JEFF_HUSBAND_RE.finditer(text):
        add(m.start(), m.end(), m.group(0), "haley", "relationship_label", "husband", classify(m))

    for m in _JEFF_BOYFRIEND_RE.finditer(text):
        add(m.start(), m.end(), m.group(0), "haley", "relationship_label", "boyfriend", classify(m))

    for m in _FATHER_RE.finditer(text):
        after = text[m.end():m.end() + 20]
        if re.match(r"(?:-in-law\b|\s+figure\b)", after, re.IGNORECASE):
            continue
        add(m.start(), m.end(), m.group(0), "haley", "biological_father", "male", classify(m))

    for m in _HALEY_FOX_TRAIT_RE.finditer(text):
        add(m.start(), m.end(), m.group(0), "haley", "fox_trait_manifestation", "fox", classify(m))

    for m in _FOX_SON_RE.finditer(text):
        add(m.start(), m.end(), m.group(0), "rainee", "biological_son", "son", classify(m))

    for m in _ATTRACTION_RE.finditer(text):
        add(m.start(), m.end(), m.group(0), "haley", "romantic_attraction", "jeff", classify(m))

    return validate_claims(claims, state)
