"""
Paragraph-level prose conditioning.

The engine works on plain text: paragraphs are separated by blank lines. Each flagged
paragraph is rewritten on its own, validated, and optionally applied by character offset so
that everything outside the paragraph is untouched.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .diagnostics import ProseDiagnosticsAnalyzer
from .exemplars import block as exemplars_block, select as select_negatives
from .guards import introduced_entities, personification_issues, preserves_facts, token_overlap
from .imagery import mask as mask_imagery, retained as retained_images, vehicles
from .invariant_gate import InvariantGate
from .models import ProseRewriteRequest, SpanCategory
from .prompt_assembler import PromptAssembler
from .semantic_drive import ReferencePassage, SemanticDrive
from .strength import Strength, get as get_strength
from .voice.strength_map import StrengthMap, missing_frozen
from .styleprint import distance as style_distance, fingerprint, load_model
from .style_engine import StyleProfile
from .voice.tics import blacklisted_cliches

MIN_RATIO = 0.4
MAX_RATIO = 2.2
MIN_CHARS = 80
MAX_CHARS = 6000

_PARAGRAPH = re.compile(r"[^\n](?:[^\n]|\n(?!\n))*")


def scene_polish_prompt(continuation, laws, observation=None, craft_cards=()):
    """Shape a single bounded polish of an already validated scene draft."""
    directions = {card['beat']: card['turn']['direction'] for card in craft_cards}
    guide = [f"{turn['stage']}\n  {directions[turn['id']]}" for turn in continuation['plan']['turns']
             if turn['id'] in directions]
    return (
        'Polish the saved rough scene for cadence, comic timing and subtext. Return the full scene text. '
        'Keep every existing line in its original order and beat, including every Action Name and dialogue prefix. '
        'Copy headings, locations and unprefixed authored stage facts exactly. Revise only the wording after Action Name '
        'or a speaker prefix. Preserve the original action, participants, facts and relationship in each line. '
        'Keep the distinctions among the characters. Leave unchanged any line where polishing would change its meaning. '
        'Stop at the end of the rough draft.\n\n'
        + 'APPLICABLE WORLD LAWS\n' + '\n'.join(law['statement'] for law in laws)
        + ('\n\nBOOK CADENCE OBSERVATIONS\n' + json.dumps(observation, ensure_ascii=False) if observation else '')
        + ('\n\nBEAT CRAFT\n' + '\n'.join(guide) if guide else '')
        + '\n\nROUGH DRAFT\n' + continuation['polish']['text']
    )


@dataclass
class Proposal:
    index: int
    start: int
    end: int
    original: str
    proposed: str
    warnings: List[str]
    accepted: bool
    reason: str
    references: List[str] = field(default_factory=list)
    original_similarity: float = 0.0
    rewrite_similarity: float = 0.0
    style_before: float = 0.0
    style_after: float = 0.0
    retained_imagery: List[str] = field(default_factory=list)
    op: str = "replace"
    removed_text: str = ""
    span_offsets: Tuple[int, int] = (0, 0)
    gate_results: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "original": self.original,
            "proposed": self.proposed,
            "warnings": self.warnings,
            "accepted": self.accepted,
            "reason": self.reason,
            "references": self.references,
            "original_similarity": round(self.original_similarity, 4),
            "rewrite_similarity": round(self.rewrite_similarity, 4),
            "style_before": round(self.style_before, 4),
            "style_after": round(self.style_after, 4),
            "retained_imagery": self.retained_imagery,
            "op": self.op,
            "removed_text": self.removed_text,
            "span_offsets": list(self.span_offsets),
            "gate_results": self.gate_results,
            "author_decision": "pending",
        }


def paragraph_spans(text: str) -> List[Tuple[int, int]]:
    """Character spans of blank-line-separated paragraphs."""
    return [(match.start(), match.end()) for match in _PARAGRAPH.finditer(text)]


def _unbalanced_quotes(text: str) -> bool:
    quotes = text.count('"') + text.count("\u201c") + text.count("\u201d")
    return quotes % 2 == 1


def _tidy_candidate(original: str, candidate: str) -> str:
    """Collapses whitespace and removes stray wrapping quotes the model may add."""
    text = " ".join(candidate.split())
    if text.startswith('"') and not original.lstrip().startswith('"'):
        text = text[1:].lstrip()
    if text.endswith('"') and not original.rstrip().endswith('"'):
        text = text[:-1].rstrip()
    return text




_DIALOGUE = re.compile(r"^\s*(?:[-\u2014\"\u201c]|[A-Z][A-Za-z .'\-]{0,24}:)")
_DELETION_PATTERNS = [
    re.compile(r",\s+(?!(?:nothing|something|anything|everything|morning|evening|king|thing|ring|spring)\b)[a-z]+ing\b[^.;!?]*[.;!?]?"),
    re.compile(
        r"\b(?:She|He|They|It|I|We|You)\s+(?:noticed|felt|heard|saw|realized|seemed|watched|"
        r"thought|knew|wondered|notices|feels|hears|sees|realizes|seems|watches|thinks|knows|"
        r"wonders)\b[^.;!?]*[.;!?]?"
    ),
    re.compile(r"\b(?:Beat|A beat)\.\s*"),
]


def is_dialogue(text: str) -> bool:
    """A cue, a dash line or a quoted line: correction must not rewrite it by default."""
    return bool(_DIALOGUE.match(text.strip()))


def _deletion_candidate(core: str):
    """Return (candidate, removed_text, offsets) for a cut-first proposal, or None."""
    spans = []
    for pattern in _DELETION_PATTERNS:
        for match in pattern.finditer(core):
            if match.end() > match.start():
                spans.append((match.start(), match.end()))
    if not spans:
        return None
    spans.sort()
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    candidate = core
    for start, end in reversed(merged):
        candidate = candidate[:start] + candidate[end:]
    candidate = " ".join(candidate.split())
    candidate = re.sub(r"\s+([,.;!?])", r"\1", candidate)
    candidate = re.sub(r"([,.;!?])\1+", r"\1", candidate).strip(" ,;")
    if not candidate or candidate == core or len(candidate) < 0.5 * len(core):
        return None
    removed = " ".join(core[start:end] for start, end in merged).strip()
    return candidate, removed, (merged[0][0], merged[-1][1])


def persist_proposals(
    proposals: List["Proposal"],
    path="eval/proposals.jsonl",
    source: str = "",
    text_before: str = "",
    text_after: str = "",
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    with target.open("a", encoding="utf-8") as handle:
        for proposal in proposals:
            row = proposal.to_dict()
            row["source"] = source
            row["ts"] = stamp
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    try:
        from telemetry.engine_run_logger import EngineRunLogger
        from .diagnostics import ProseDiagnosticsAnalyzer
        EngineRunLogger.log_run(
            source_document=source or str(path),
            proposals=proposals,
            input_text=text_before,
            output_text=text_after,
            burstiness_calculator=lambda t: ProseDiagnosticsAnalyzer.analyze(t).burstiness_score if t else 0.0,
            cliche_findings=[blacklisted_cliches(p.proposed) if p.proposed else [] for p in proposals],
        )
    except Exception:
        pass

    return target


def plan_conditioning(
    text: str,
    provider,
    profile: StyleProfile,
    drive: Optional[SemanticDrive] = None,
    limit: Optional[int] = None,
    min_chars: int = MIN_CHARS,
    max_chars: int = MAX_CHARS,
    strength: str = "standard",
    influence=None,
    contrastive: bool = False,
    books_dir: str = "books",
    strength_map: StrengthMap | None = None,
    frozen: Sequence[str] = (),
    extra_context: str = "",
    world=None,
    house=None,
    allow_dialogue: bool = False,
) -> List[Proposal]:
    """Rewrites each flagged paragraph; never mutates the source text.

    Correction is cut-first: a matching tell is deleted before any regeneration. Dialogue is
    FROZEN by default because in comedy the dialogue is the joke; pass allow_dialogue=True
    (CLI: --allow-dialogue) to propose changes to it.
    """
    preset_default: Strength = get_strength(strength)
    if drive is not None:
        from .reference_policy import prompt_purposes, restricted_drive
        policy = getattr(drive, "reference_policy", None)
        purposes = getattr(drive, "reference_purposes", None)
        if policy is None or purposes is None:
            raise ValueError("Reference drive has no source policy; configure reference eligibility first.")
        if not set(prompt_purposes(getattr(provider, "name", None))) <= set(purposes):
            raise ValueError("Reference drive is not authorized for this provider and prompt.")
        drive = restricted_drive(drive, policy, purposes, influence)
    books_path = Path(books_dir)
    voice_path = books_path / "voice_card.md"
    voice_card = voice_path.read_text(encoding="utf-8") if voice_path.is_file() else ""
    style_model = load_model(books_path)
    spans = paragraph_spans(text)
    proposals: List[Proposal] = []
    attempted = 0
    allowed_entities = set()
    if world is not None:
        for name, data in getattr(world, "characters", {}).items():
            allowed_entities.add(name)
            allowed_entities.update(data.get("aliases") or [])

    for index, (start, end) in enumerate(spans):
        core = text[start:end].strip()
        if len(core) < min_chars or len(core) > max_chars:
            continue
        preset = preset_default
        if strength_map is not None:
            effective = strength_map.policy_for(index, core)
            if effective.skip:
                continue
            preset = get_strength(effective.preset)
        if is_dialogue(core) and not allow_dialogue:
            continue
        if is_dialogue(core) and any(span.strip() and span.strip() in core for span in frozen):
            continue
        report = ProseDiagnosticsAnalyzer.analyze(core)
        if not report.warnings:
            continue
        if limit is not None and attempted >= limit:
            break
        attempted += 1

        deletion = _deletion_candidate(core)
        if deletion is not None:
            candidate, removed, offsets = deletion
            delete_reason = ""
            if not preserves_facts(core, candidate)[0]:
                delete_reason = "deletion drops facts: " + ", ".join(preserves_facts(core, candidate)[1][:3])
            elif missing_frozen(core, candidate, frozen):
                delete_reason = "deletion drops a frozen span"
            elif world is not None and (world.violations(candidate) or world.plausibility(candidate)):
                delete_reason = "deletion breaks world state"
            elif house is not None and house.check_scene([candidate]):
                delete_reason = "deletion breaks staging"
            if not delete_reason:
                proposals.append(
                    Proposal(
                        index, start, end, core, candidate, report.warnings, True,
                        "deleted: " + removed[:100], [], 0.0, 0.0, 0.0, 0.0, [],
                        op="delete", removed_text=removed, span_offsets=offsets,
                    )
                )
                continue

        request = ProseRewriteRequest(
            request_id=f"cond_{uuid.uuid4().hex[:8]}",
            project_id="prose_engine",
            document_id="document",
            base_revision=1,
            target_span_id=f"para-{index}",
            original_text=core,
            category=SpanCategory.GENERAL,
            target_psychic_distance=profile.target_psychic_distance,
            style_profile_id=profile.profile_id,
        )
        scorer = getattr(drive, "score_text", None) or getattr(getattr(drive, "index", None), "score", None)
        try:
            references: List[ReferencePassage] = (
                drive.retrieve_passages(profile.profile_id, core, max_results=preset.references, influence=influence)
                if drive else []
            )
            original_score = scorer(core) if scorer else None
            original_similarity = float(original_score["mean_top"]) if original_score else 0.0
            if not math.isfinite(original_similarity):
                raise ValueError("Reference scorer returned a non-finite value")
        except Exception as exc:
            proposals.append(Proposal(index, start, end, core, "", report.warnings, False,
                                      f"retrieval unavailable before generation: {type(exc).__name__}: {exc}"[:180]))
            continue
        prompt = PromptAssembler.assemble(
            request=request,
            diagnostics=report,
            style_profile=profile,
            approved_edits=[],
            reference_passages=references,
        )
        if voice_card:
            prompt += "\n\n" + voice_card
        if extra_context:
            prompt += "\n\n" + extra_context
        prompt += "\n\n" + preset.directive
        forbidden = sorted(vehicles(core)) if preset.name == "rebuild" else []
        if forbidden:
            prompt += (
                "\n\nORIGINAL WITH COMPARISONS REMOVED (write from these facts, invent your own "
                "physical detail): " + mask_imagery(core)
            )
        if forbidden:
            prompt += (
                "\n\nFORBIDDEN IMAGES (the original's comparisons; do not reuse or reword them): "
                + ", ".join(forbidden)
            )
        if contrastive:
            negatives = select_negatives(report.warnings)
            negative_block = exemplars_block(negatives)
            if negative_block:
                prompt += "\n\n" + negative_block

        from .providers.deepseek import BudgetExceeded

        try:
            raw = provider.generate_rewrite(request, prompt)
        except BudgetExceeded:
            raise
        except Exception as exc:  # a provider failure must not abort the pass
            proposals.append(
                Proposal(index, start, end, core, "", report.warnings, False, f"provider error: {exc}"[:180])
            )
            continue

        candidate = _tidy_candidate(core, InvariantGate.clean_candidate_text(raw))
        ok, violations, _cleaned = InvariantGate.audit_rewrite(candidate, request)
        overlap = token_overlap(core, candidate) if candidate else 0.0
        retained_list = sorted(retained_images(core, candidate)) if candidate else []
        style_before = style_distance(fingerprint(core), style_model) if style_model else 0.0
        style_after = (
            style_distance(fingerprint(candidate), style_model)
            if style_model and candidate
            else 0.0
        )
        score_error = None
        try:
            rewrite_score = scorer(candidate) if scorer and candidate else None
            rewrite_similarity = float(rewrite_score["mean_top"]) if rewrite_score else 0.0
            if not math.isfinite(rewrite_similarity):
                raise ValueError("Reference scorer returned a non-finite value")
        except Exception as exc:
            rewrite_similarity = 0.0
            score_error = f"retrieval score unavailable: {type(exc).__name__}: {exc}"[:160]
        candidate_report = ProseDiagnosticsAnalyzer.analyze(candidate) if candidate else None
        regressed = bool(
            candidate_report
            and (
                candidate_report.filter_word_count > report.filter_word_count
                or len(candidate_report.label_examples) > len(report.label_examples)
            )
        )

        if score_error:
            reason = score_error
        elif not candidate:
            reason = "empty candidate"
        elif not ok:
            reason = "; ".join(violations)[:160]
        elif candidate == core:
            reason = "unchanged"
        elif _unbalanced_quotes(candidate):
            reason = "unbalanced quotation marks"
        elif blacklisted_cliches(candidate):
            reason = "blacklisted cliché: " + ", ".join(blacklisted_cliches(candidate)[:2])
        elif introduced_entities(core, candidate, allowed_entities):
            reason = "introduces new entities: " + ", ".join(introduced_entities(core, candidate, allowed_entities)[:3])
        elif personification_issues(candidate):
            reason = "coherence: " + "; ".join(personification_issues(candidate)[:2])
        elif world is not None and (world.violations(candidate) or world.plausibility(candidate)):
            breaks = world.violations(candidate) + world.plausibility(candidate)
            reason = "breaks world state: " + "; ".join(f"{phrase} ({why})" for phrase, why in breaks[:2])
        elif house is not None and house.check_scene([candidate]):
            reason = "staging: " + "; ".join(house.check_scene([candidate])[:2])
        elif missing_frozen(core, candidate, frozen):
            reason = "drops frozen span: " + "; ".join(missing_frozen(core, candidate, frozen)[:2])
        elif not preserves_facts(core, candidate)[0]:
            reason = "drops facts: " + ", ".join(preserves_facts(core, candidate)[1][:3])
        elif style_model and len(core) >= 150 and style_after > style_before + 0.75:
            reason = (
                f"off-voice (style distance {style_before:.2f} -> {style_after:.2f}; "
                f"the rewrite moved away from the corpus)"
            )
        elif preset.max_overlap and overlap > preset.max_overlap:
            reason = (
                f"too close to the original (overlap {overlap:.2f} > {preset.max_overlap:.2f}); "
                f"rewrite from the facts, not the sentences"
            )
        elif preset.name == "rebuild" and retained_list:
            reason = "retains the original's imagery: " + ", ".join(retained_list[:5])
        elif regressed:
            reason = "rewrite introduced filter words or emotion labels"
        elif (scorer and getattr(drive, "similarity_threshold", 0.10) is not None and
              rewrite_similarity < original_similarity - getattr(drive, "similarity_threshold", 0.10)):
            reason = (
                f"off-voice (corpus similarity {original_similarity:.2f} -> "
                f"{rewrite_similarity:.2f})"
            )
        else:
            ratio = len(candidate) / max(1, len(core))
            reason = (
                ""
                if preset.min_ratio <= ratio <= preset.max_ratio
                else f"length ratio {ratio:.2f} outside {preset.min_ratio:.2f}-{preset.max_ratio:.2f}"
            )
        accepted = not reason
        exportable_references = [
            passage.text for passage in references
            if drive.reference_policy.allows(
                {"source_id": passage.provenance.get("source_id")}, ("export",), influence)
        ] if drive is not None else []
        proposals.append(
            Proposal(
                index, start, end, core, candidate, report.warnings, accepted, reason or "ok",
                exportable_references, original_similarity, rewrite_similarity,
                style_before, style_after, retained_list, op="replace",
            )
        )

    return proposals


def apply_proposals(text: str, proposals: List[Proposal]) -> Tuple[str, int]:
    """Replaces accepted paragraphs by offset, back to front, leaving all else untouched."""
    accepted = [proposal for proposal in proposals if proposal.accepted]
    updated = text
    for proposal in sorted(accepted, key=lambda item: -item.start):
        updated = updated[: proposal.start] + proposal.proposed + updated[proposal.end :]
    return updated, len(accepted)


def apply_proposals_checked(
    text: str, proposals: List[Proposal], world=None, house=None, plan=None
) -> Tuple[str, int, List[Tuple[int, List[str]]]]:
    """Apply accepted proposals one at a time; roll back any that introduce NEW document issues."""
    from .voice.recheck import document_issues

    base = set(document_issues(text, world, house, plan))
    updated = text
    applied = 0
    rollbacks: List[Tuple[int, List[str]]] = []
    accepted = [proposal for proposal in proposals if proposal.accepted]
    for proposal in sorted(accepted, key=lambda item: -item.start):
        candidate = updated[: proposal.start] + proposal.proposed + updated[proposal.end:]
        new_issues = sorted(set(document_issues(candidate, world, house, plan)) - base)
        if new_issues:
            rollbacks.append((proposal.index, new_issues[:2]))
            continue
        updated = candidate
        applied += 1
    return updated, applied, rollbacks


def text_metrics(text: str) -> Dict:
    report = ProseDiagnosticsAnalyzer.analyze(text)
    return {
        "filter_words": report.filter_word_count,
        "emotion_labels": len(report.label_examples),
        "warnings": len(report.warnings),
        "burstiness": round(report.burstiness_score, 2),
        "mean_sentence_length": round(report.average_sentence_length, 2),
        "sensory_details": report.sensory_details_count,
        "composite_slop_score": round(report.composite_slop_score, 2),
    }


def review_html(title: str, proposals: List[Proposal]) -> str:
    rows = []
    for proposal in proposals:
        status = "accepted" if proposal.accepted else f"skipped ({proposal.reason})"
        rows.append(
            "<article>"
            f'<div class="meta">¶{proposal.index} · {status} · voice {proposal.original_similarity:.2f} -> '
            f'{proposal.rewrite_similarity:.2f} · {"; ".join(proposal.warnings[:2])}</div>'
            f'<div class="orig">{proposal.original[:600]}</div>'
            f'<div class="new">{proposal.proposed[:600] or "—"}</div>'
            + (
                '<div class="ref">corpus: '
                + " | ".join(text[:90] for text in proposal.references[:2])
                + "</div>"
                if proposal.references
                else ""
            )
            + "</article>"
        )
    accepted = sum(1 for proposal in proposals if proposal.accepted)
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{title} - conditioning review</title><style>"
        "body{background:#0b1120;color:#e2e8f0;font-family:ui-sans-serif,system-ui;padding:24px;max-width:1100px;margin:auto}"
        "h1{color:#fbbf24;font-size:20px}article{border:1px solid #334155;border-radius:10px;padding:12px;margin:12px 0}"
        ".meta{font:11px ui-monospace,Consolas;color:#94a3b8;margin-bottom:6px}"
        ".orig{color:#f87171;text-decoration:line-through;margin:4px 0}.new{color:#4ade80}"
        "</style></head><body>"
        f"<h1>{title} - conditioning proposals</h1>"
        f'<p class="meta">{accepted} accepted / {len(proposals)} flagged paragraphs</p>'
        + "".join(rows)
        + "</body></html>"
    )


def run_conditioning(
    source: str | Path,
    out_dir: str | Path,
    provider,
    profile: StyleProfile,
    drive: Optional[SemanticDrive] = None,
    apply: bool = False,
    limit: Optional[int] = None,
    title: Optional[str] = None,
    strength: str = "standard",
    influence=None,
    contrastive: bool = False,
    books_dir: str = "books",
    strength_map: StrengthMap | None = None,
    frozen: Sequence[str] = (),
    extra_context: str = "",
    world=None,
    house=None,
    allow_dialogue: bool = False,
) -> Dict:
    """Plans proposals, writes the review artifacts, and optionally the conditioned text."""
    source_path = Path(source)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    text = source_path.read_text(encoding="utf-8")
    title = title or source_path.stem

    proposals = plan_conditioning(
        text,
        provider,
        profile,
        drive=drive,
        limit=limit,
        strength=strength,
        influence=influence,
        contrastive=contrastive,
        books_dir=books_dir,
        strength_map=strength_map,
        frozen=frozen,
        extra_context=extra_context,
        world=world,
        house=house,
        allow_dialogue=allow_dialogue,
    )
    persist_proposals(proposals, "eval/proposals.jsonl", source_path.name)
    (out / "proposals.json").write_text(
        json.dumps([proposal.to_dict() for proposal in proposals], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out / "review.html").write_text(review_html(title, proposals), encoding="utf-8")

    references_available = 0
    if drive is not None:
        if hasattr(drive, "_passages_by_profile"):
            references_available = len(drive._passages_by_profile.get(profile.profile_id, {}))
        elif getattr(drive, "index", None) is not None:
            references_available = int(drive.index.vectors.shape[0])

    scored = [p for p in proposals if p.original_similarity]
    result: Dict = {
        "source": str(source_path),
        "profile": profile.profile_id,
        "strength": strength,
        "voice_before": round(sum(p.original_similarity for p in scored) / len(scored), 4) if scored else 0.0,
        "voice_after": round(
            sum(p.rewrite_similarity for p in scored if p.accepted) / max(1, sum(1 for p in scored if p.accepted)), 4
        ) if scored else 0.0,
        "references": references_available,
        "flagged": len(proposals),
        "accepted": sum(1 for proposal in proposals if proposal.accepted),
        "applied": 0,
        "before": text_metrics(text),
        "artifacts": {"proposals": str(out / "proposals.json"), "review": str(out / "review.html")},
    }

    if apply and result["accepted"]:
        conditioned, applied = apply_proposals(text, proposals)
        result["applied"] = applied
        result["after"] = text_metrics(conditioned)
        conditioned_path = out / "conditioned.md"
        conditioned_path.write_text(conditioned, encoding="utf-8")
        result["artifacts"]["conditioned"] = str(conditioned_path)
        checks: List[str] = []
        if world is not None:
            checks += [f"{phrase} ({why})" for phrase, why in world.violations(conditioned) + world.plausibility(conditioned)]
        if house is not None:
            chunks = [conditioned[a:b].strip() for a, b in paragraph_spans(conditioned)]
            checks += house.check_scene(chunks)
        result["document_checks"] = checks
        (out / "conditioned_report.json").write_text(
            json.dumps({"before": result["before"], "after": result["after"]}, indent=2),
            encoding="utf-8",
        )

    (out / "report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


# -----------------------------------------------------------------------------
# M2.5 Positive Rhythm Skeleton & Surgical Pass 5 Rewrite
# -----------------------------------------------------------------------------

def _count_manifest_books(books_dir: str | Path = "books") -> int:
    manifest_path = Path(books_dir) / "manifest.json"
    if manifest_path.is_file():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("books"), list):
                return len(payload["books"])
        except Exception:
            pass
    try:
        from .library_indexes import library_status
        st = library_status(books_dir)
        return int(st.get("eligible_books") or st.get("total_books") or 0)
    except Exception:
        return 0


def build_rhythm_skeleton(
    style_card: Optional[Dict] = None,
    token_budget: int = 130,
    books_dir: str = "books",
) -> Dict:
    """Build a compact positive cadence/burstiness skeleton within token_budget."""
    card = style_card or {}
    books_count = _count_manifest_books(books_dir)
    target_sigma = float(card.get("target_burstiness", 4.5))
    lens = str(card.get("lens") or "dry-comic-noir").strip()
    skeleton = (
        f"RHYTHM[{lens}|lib={books_count}]: vary sentence lengths (sigma>={target_sigma:.1f}), "
        "pair sharp 3-5 word action beats with 14-20 word concrete sensory observations, "
        "cut causal lecturing and binary contrasts, keep dialogue raw."
    )
    max_chars = max(40, int(token_budget) * 4)
    if len(skeleton) > max_chars:
        skeleton = skeleton[: max_chars - 3].rstrip() + "..."
    approx_tokens = max(1, (len(skeleton) + 3) // 4)
    return {
        "skeleton": skeleton,
        "approx_tokens": approx_tokens,
        "within_budget": approx_tokens <= token_budget,
        "library_books_indexed": books_count,
    }


_PASS5_SURGICAL_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # Essayistic transitions
    (re.compile(r"\b(?:Because of this|Due to this|As a result of this),?\s+", re.IGNORECASE), ""),
    (re.compile(r"\b(?:It is worth noting that|In order to understand)\s+", re.IGNORECASE), ""),
    # Binary contrast formulas: "Not X, but Y" / "It wasn't X—it was Y"
    (re.compile(r"\b[Nn]ot\s+(?:a\s+|an\s+|just\s+)?[a-z]+(?:\s+[a-z]+){0,2},\s+but\s+(?:rather\s+)?((?:a\s+|an\s+)?[a-z]+)\b"), r"\1"),
    (re.compile(r"\b(?:[Ii]t\s+)?(?:wasn'?t|isn'?t)\s+[^.!?\n]{2,40}(?:—|--|,)\s*(?:it\s+)?(was|is)\b"), r"It \1"),
    (re.compile(r"\bless\s+(?:(?:of\s+)?(?:a|an)\s+)?[a-z]+\s+and\s+more\s+((?:(?:of\s+)?(?:a|an)\s+)?[a-z]+)\b", re.IGNORECASE), r"\1"),
    # Weak dangling participial tails
    (re.compile(r",\s*(?:leaving|creating|sending|causing|resulting\s+in)\s+[a-z\s]{4,35}(?=[.?!])", re.IGNORECASE), ""),
    # Hard-banned AI-isms & vocab-maxxing
    (re.compile(r"\b(?:couldn't|can't)\s+help\s+but\s+", re.IGNORECASE), ""),
    (re.compile(r"\b(?:almost\s+as\s+if|as\s+if\s+on\s+cue)\s*,?\s*", re.IGNORECASE), ""),
    (re.compile(r"\b(?:a\s+testament\s+to|tapestry\s+of|symphony\s+of|kaleidoscope\s+of|myriad\s+of|plethora\s+of)\s+", re.IGNORECASE), ""),
    (re.compile(r"\b(?:unfazed|visceral|labyrinthine|unwavering)\s+", re.IGNORECASE), ""),
    (re.compile(r"\b(?:palpable\s+tension|deafening\s+silence|quiet\s+devastation)\b", re.IGNORECASE), "stillness"),
    # False agency
    (re.compile(r"\b(?:the\s+)?(silence|room|air|shadow|shadows|darkness|wall|walls|clock|hallway|mirror)\s+(?:demanded|whispered|judged|waited|watched|insisted|mocked|knew|remembered)\b", re.IGNORECASE), r"\1 hung"),
]


def _clean_segment_pass5(segment: str) -> str:
    updated = segment
    for pat, repl in _PASS5_SURGICAL_PATTERNS:
        updated = pat.sub(repl, updated)
    # Collapse double spaces on non-newline runs while keeping paragraph breaks
    updated = re.sub(r"[ \t]{2,}", " ", updated)
    updated = re.sub(r" ([.,!?;:])", r"\1", updated)
    # Capitalize start of sentence after stripped leading transition
    updated = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), updated)
    return updated


def surgical_pass5_rewrite(
    text: str,
    frozen_spans: Sequence[str] = (),
    rewriter_fn=None,
) -> Dict:
    """Apply span-level Pass 5 anti-slop cleanup + mechanical byte splice honoring 0% LOCK spans."""
    from .linter import compute_composite_slop_score

    before = compute_composite_slop_score(text)

    # Locate all frozen ranges so they are mechanically preserved byte-for-byte
    locked_ranges: List[Tuple[int, int]] = []
    for span in frozen_spans:
        if not span:
            continue
        start_idx = 0
        while True:
            pos = text.find(span, start_idx)
            if pos == -1:
                break
            locked_ranges.append((pos, pos + len(span)))
            start_idx = pos + len(span)

    # Merge overlapping locked ranges
    locked_ranges.sort()
    merged_locked: List[Tuple[int, int]] = []
    for s, e in locked_ranges:
        if merged_locked and s <= merged_locked[-1][1]:
            merged_locked[-1] = (merged_locked[-1][0], max(merged_locked[-1][1], e))
        else:
            merged_locked.append((s, e))

    # Splice: rewrite only unlocked gaps, copy locked spans verbatim
    chunks: List[str] = []
    cursor = 0
    for s, e in merged_locked:
        if s > cursor:
            gap = text[cursor:s]
            chunks.append(rewriter_fn(gap) if rewriter_fn is not None else _clean_segment_pass5(gap))
        chunks.append(text[s:e])
        cursor = e
    if cursor < len(text):
        tail = text[cursor:]
        chunks.append(rewriter_fn(tail) if rewriter_fn is not None else _clean_segment_pass5(tail))

    rewritten = "".join(chunks)
    locked_bytes_intact = all(span in rewritten for span in frozen_spans if span)
    after = compute_composite_slop_score(rewritten)

    return {
        "text": rewritten,
        "slop_before": before["score"],
        "slop_after": after["score"],
        "slop_delta": round(after["score"] - before["score"], 2),
        "burstiness_before": before["burstiness"],
        "burstiness_after": after["burstiness"],
        "locked_bytes_intact": locked_bytes_intact,
        "before_report": before,
        "after_report": after,
    }


def polish_cook_candidate(text, frozen_spans):
    """Apply surgical polish to narration while retaining spoken bytes."""
    import re

    dialogue = re.findall(r'(?m)^[ \t]*[*@]*[^\W\d_][\w .’\'*-]{0,42}:[^\r\n]*', text)
    quotes = re.findall(r'“[^”\r\n]*”|"[^"\r\n]*"', text)
    protected = tuple(dict.fromkeys([*frozen_spans, *dialogue, *quotes]))
    result = surgical_pass5_rewrite(text, frozen_spans=protected)
    result['locked_bytes_intact'] = result['locked_bytes_intact'] and all(
        text.count(span) == result['text'].count(span) for span in protected if span
    )
    return result
