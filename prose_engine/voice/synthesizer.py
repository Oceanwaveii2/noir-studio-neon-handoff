"""
De Novo Scene Synthesizer (Milestone M12).

Separates scenes into an Inviolable Dialogue Skeleton (100% frozen string bytecode)
and Dramatic Action Beats, synthesizing fresh descriptive prose through an Author Lens
without clause-by-clause mirroring of previous drafts.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .best_of_n import Candidate, score_text, select as select_best, select_all as select_all_best
from .injection import format_injection_prompt, sample_idioms, sample_rhythm
from .lens import AuthorLens, get_lens
from .slop_critic import SlopCritic
from .tics import blacklisted_cliches

MAX_CRAFT_BRIEF_BYTES = 6144

DIALOGUE_PATTERN = re.compile(
    r"^([A-Z0-9\s‑\-\(\)\'\.]+?)\\\s*(?:\(([^)]+)\)\\\s*)?(.*)$"
)
_COLON_DIALOGUE_PATTERN = re.compile(
    r'^([A-Z][A-Z0-9 .\'\-]{0,38}):[ \t]*(?:\(([^)]+)\)[ \t]*)?(?:"([^"\r\n]+)"|\u201c([^\u201d\r\n]+)\u201d|(\S.*))$'
)
_QUOTE_ONLY_PATTERN = re.compile(r'"([^"\r\n]{2,})"|\u201c([^\u201d\r\n]{2,})\u201d')


@dataclass(frozen=True)
class DialogueLine:
    index: int
    speaker: str
    parenthetical: str
    text: str

    @property
    def clean_text(self) -> str:
        return unicodedata.normalize("NFKC", self.text).strip()


def extract_dialogue_skeleton(script_text: str) -> List[DialogueLine]:
    """Extract spoken dialogue lines from backslash screenplay cues, colon cues, or quoted lines."""
    lines: List[DialogueLine] = []
    idx = 0
    for raw_line in script_text.splitlines():
        line = raw_line.strip()
        if not line or "\\" not in line:
            continue
        match = DIALOGUE_PATTERN.match(line)
        if match:
            speaker = match.group(1).strip()
            paren = (match.group(2) or "").strip()
            speech = match.group(3).strip()
            if speech:
                lines.append(DialogueLine(index=idx, speaker=speaker, parenthetical=paren, text=speech))
                idx += 1
    if lines:
        return lines

    for raw_line in script_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        cmatch = _COLON_DIALOGUE_PATTERN.match(line)
        if cmatch:
            speaker = cmatch.group(1).strip()
            paren = (cmatch.group(2) or "").strip()
            speech = (cmatch.group(3) or cmatch.group(4) or cmatch.group(5) or "").strip()
            if speech:
                lines.append(DialogueLine(index=idx, speaker=speaker, parenthetical=paren, text=speech))
                idx += 1
            continue
        for qm in _QUOTE_ONLY_PATTERN.finditer(line):
            speech = (qm.group(1) or qm.group(2) or "").strip()
            if speech:
                lines.append(DialogueLine(index=idx, speaker="SPEAKER", parenthetical="", text=speech))
                idx += 1
    return lines


def normalize_for_comparison(text: str) -> str:
    """Normalizes Unicode dashes, quotes, and whitespace for robust dialogue verification."""
    norm = unicodedata.normalize("NFKC", text)
    # Standardize curly quotes, dashes, and ellipses
    norm = norm.replace("‑", "-").replace("—", "--").replace("–", "--")
    norm = norm.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    norm = norm.replace("…", "...").replace("\u2011", "-")
    # Collapse multiple whitespace
    norm = re.sub(r"\s+", " ", norm)
    return norm.strip()


def verify_dialogue_invariant(
    skeleton: Sequence[DialogueLine],
    prose: str,
    *,
    require_order: bool = False,
) -> Tuple[bool, List[str]]:
    """Verify 100% of spoken lines appear verbatim (and optionally in sequence order) in prose."""
    norm_prose = normalize_for_comparison(prose)
    missing: List[str] = []
    cursor = 0
    for line in skeleton:
        norm_line = normalize_for_comparison(line.text)
        if require_order:
            pos = norm_prose.find(norm_line, cursor)
            if pos < 0:
                missing.append(f"{line.speaker}: \"{line.text}\"")
            else:
                cursor = pos + len(norm_line)
        elif norm_line not in norm_prose:
            missing.append(f"{line.speaker}: \"{line.text}\"")
    return len(missing) == 0, missing


@dataclass
class DramaticBeat:
    beat_id: str
    action_summary: str
    props: List[str] = field(default_factory=list)
    dialogue: List[DialogueLine] = field(default_factory=list)


@dataclass(frozen=True)
class CraftBrief:
    """Compact <6 KB prompt brief binding lens craft cues, dialogue skeleton, and neurosymbolic guards."""

    scene_heading: str
    lens_id: str
    viewpoint: Optional[str]
    max_bytes: int
    byte_size: int
    brief_sha256: str
    prompt: str
    trimmed_sections: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scene_heading": self.scene_heading,
            "lens_id": self.lens_id,
            "viewpoint": self.viewpoint,
            "max_bytes": self.max_bytes,
            "byte_size": self.byte_size,
            "brief_sha256": self.brief_sha256,
            "trimmed_sections": list(self.trimmed_sections),
            "prompt": self.prompt,
        }


def compile_craft_brief(
    scene_heading: str,
    beats: Sequence[DramaticBeat | str],
    skeleton: Sequence[DialogueLine] = (),
    *,
    lens_id: str = "irby",
    viewpoint: Optional[str] = None,
    world_laws: Sequence[str] = (),
    mind_directives: Sequence[str] = (),
    epistemic_withheld: Sequence[str] = (),
    craft_cues: Sequence[str] = (),
    max_bytes: int = MAX_CRAFT_BRIEF_BYTES,
    seed: Optional[int] = None,
) -> CraftBrief:
    """Compile a self-contained De Novo CraftBrief guaranteed <= max_bytes (default 6144 bytes UTF-8)."""
    if type(max_bytes) is not int or not 512 <= max_bytes <= MAX_CRAFT_BRIEF_BYTES:
        raise ValueError(f"max_bytes must be between 512 and {MAX_CRAFT_BRIEF_BYTES}")

    lens = get_lens(lens_id)
    rhythm_cue = sample_rhythm(lens.id, seed=seed)
    idioms = sample_idioms(lens.id, count=3, seed=seed)

    beat_items: List[str] = []
    for i, b in enumerate(beats, 1):
        if isinstance(b, DramaticBeat):
            props = f" [{', '.join(b.props)}]" if b.props else ""
            beat_items.append(f"- [{b.beat_id}] {b.action_summary.strip()}{props}")
        else:
            beat_items.append(f"- [b{i}] {str(b).strip()}")

    dial_items = [
        f'- {line.speaker}{f" ({line.parenthetical})" if line.parenthetical else ""}: "{line.text}"'
        for line in skeleton
    ]
    law_items = [f"- {w.strip()}" for w in world_laws if str(w).strip()]
    mind_items = [f"- {m.strip()}" for m in mind_directives if str(m).strip()]
    withheld_items = [f"- WITHHOLD: {u.strip()}" for u in epistemic_withheld if str(u).strip()]
    cue_items = [f"- {c.strip()}" for c in craft_cues if str(c).strip()]
    idiom_items = [f'- "{id_str}"' for id_str in idioms if str(id_str).strip()]

    def _render(
        *,
        use_idioms: List[str],
        use_cues: List[str],
        use_minds: List[str],
        use_laws: List[str],
        use_withheld: List[str],
        use_beats: List[str],
        compact_header: bool = False,
    ) -> str:
        sections = [
            f"CRAFT BRIEF | SCENE: {scene_heading} | LENS: {lens.name} ({lens.author})"
            + (f" | POV: {viewpoint}" if viewpoint else ""),
            f"RHYTHM: {rhythm_cue}",
        ]
        if not compact_header:
            sections.append(
                "BANNED SLOP: No participial tails, filter verbs, 'baritone trombone', 'pneumatic', 'hydraulic', or AI clichés."
            )
        if dial_items:
            sections.append("INVIOLABLE DIALOGUE (VERBATIM, IN ORDER):\n" + "\n".join(dial_items))
        if use_beats:
            sections.append("ACTION BEATS:\n" + "\n".join(use_beats))
        if use_minds:
            sections.append("MIND DIRECTIVES:\n" + "\n".join(use_minds))
        if use_laws:
            sections.append("WORLD LAWS:\n" + "\n".join(use_laws))
        if use_withheld:
            sections.append("EPISTEMIC BOUNDS:\n" + "\n".join(use_withheld))
        if use_cues:
            sections.append("CRAFT CUES:\n" + "\n".join(use_cues))
        if use_idioms:
            sections.append("LENS IDIOMS:\n" + "\n".join(use_idioms))
        return "\n\n".join(sections)

    cur_idioms = list(idiom_items)
    cur_cues = list(cue_items)
    cur_minds = list(mind_items)
    cur_laws = list(law_items)
    cur_withheld = list(withheld_items)
    cur_beats = list(beat_items)
    trimmed: List[str] = []

    rendered = _render(
        use_idioms=cur_idioms,
        use_cues=cur_cues,
        use_minds=cur_minds,
        use_laws=cur_laws,
        use_withheld=cur_withheld,
        use_beats=cur_beats,
    )
    trim_plan = [
        ("idioms", cur_idioms),
        ("craft_cues", cur_cues),
        ("mind_directives", cur_minds),
        ("epistemic_withheld", cur_withheld),
        ("world_laws", cur_laws),
    ]
    for label, bucket in trim_plan:
        while len(rendered.encode("utf-8")) > max_bytes and bucket:
            bucket.pop()
            if label not in trimmed:
                trimmed.append(label)
            rendered = _render(
                use_idioms=cur_idioms,
                use_cues=cur_cues,
                use_minds=cur_minds,
                use_laws=cur_laws,
                use_withheld=cur_withheld,
                use_beats=cur_beats,
            )

    if len(rendered.encode("utf-8")) > max_bytes:
        trimmed.append("compact_beats")
        cur_beats = [b[:110] + "…" if len(b) > 110 else b for b in cur_beats]
        rendered = _render(
            use_idioms=cur_idioms,
            use_cues=cur_cues,
            use_minds=cur_minds,
            use_laws=cur_laws,
            use_withheld=cur_withheld,
            use_beats=cur_beats,
            compact_header=True,
        )

    raw_bytes = rendered.encode("utf-8")
    if len(raw_bytes) > max_bytes:
        trimmed.append("byte_clamp")
        rendered = raw_bytes[:max_bytes].decode("utf-8", errors="ignore").rstrip()

    final_bytes = len(rendered.encode("utf-8"))
    digest_hex = hashlib.sha256(
        json.dumps(
            {
                "scene_heading": scene_heading,
                "lens_id": lens.id,
                "viewpoint": viewpoint,
                "dial": dial_items,
                "beats": beat_items,
                "prompt": rendered,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return CraftBrief(
        scene_heading=scene_heading,
        lens_id=lens.id,
        viewpoint=viewpoint,
        max_bytes=max_bytes,
        byte_size=final_bytes,
        brief_sha256=digest_hex,
        prompt=rendered,
        trimmed_sections=tuple(trimmed),
    )


class DeNovoSynthesizer:
    """Synthesize scene prose de novo with <6 KB craft briefs, SlopCritic, and Best-of-N ranking."""

    def __init__(self, lens_name_or_id: str = "irby", critic: Optional[SlopCritic] = None):
        self.lens: AuthorLens = get_lens(lens_name_or_id)
        self.critic: SlopCritic = critic or SlopCritic()

    def compile_brief(
        self,
        scene_heading: str,
        beats: Sequence[DramaticBeat | str],
        skeleton: Sequence[DialogueLine] = (),
        *,
        viewpoint: Optional[str] = None,
        world_laws: Sequence[str] = (),
        mind_directives: Sequence[str] = (),
        epistemic_withheld: Sequence[str] = (),
        craft_cues: Sequence[str] = (),
        max_bytes: int = MAX_CRAFT_BRIEF_BYTES,
        seed: Optional[int] = None,
    ) -> CraftBrief:
        return compile_craft_brief(
            scene_heading,
            beats,
            skeleton,
            lens_id=self.lens.id,
            viewpoint=viewpoint,
            world_laws=world_laws,
            mind_directives=mind_directives,
            epistemic_withheld=epistemic_withheld,
            craft_cues=craft_cues,
            max_bytes=max_bytes,
            seed=seed,
        )

    def assemble_brief_prompt(
        self,
        scene_heading: str,
        beats: Sequence[DramaticBeat | str],
        skeleton: Sequence[DialogueLine] = (),
        **kwargs: Any,
    ) -> str:
        return self.compile_brief(scene_heading, beats, skeleton, **kwargs).prompt

    def assemble_synthesis_prompt(
        self,
        scene_heading: str,
        beats: Sequence[DramaticBeat],
        skeleton: Sequence[DialogueLine],
        seed: Optional[int] = None,
    ) -> str:
        injection = format_injection_prompt(self.lens.id, count=4, seed=seed)

        prompt_lines = [
            f"=== SYSTEM: DE NOVO SCENE SYNTHESIZER ===",
            f"AUTHOR LENS: {self.lens.name.upper()} ({self.lens.author})",
            f"SCENE: {scene_heading}",
            "",
            "=== INVIOLABLE DIALOGUE SKELETON (0-BYTE DRIFT MANDATE) ===",
            "The following spoken dialogue lines MUST appear VERBATIM inside quotation marks in exact sequence.",
            "You are strictly forbidden from changing, omitting, paraphrasing, or swapping any spoken word:",
        ]
        for line in skeleton:
            paren_str = f" ({line.parenthetical})" if line.parenthetical else ""
            prompt_lines.append(f'- {line.speaker}{paren_str}: "{line.text}"')

        prompt_lines.extend([
            "",
            "=== DRAMATIC ACTION BEATS (WHAT PHYSICALLY HAPPENS) ===",
            "Depict the following action progression with sensory weight, comedic friction, and tactile movement:",
        ])
        for b in beats:
            prop_str = f" [Props: {', '.join(b.props)}]" if b.props else ""
            prompt_lines.append(f"- [{b.beat_id}] {b.action_summary}{prop_str}")

        prompt_lines.extend([
            "",
            injection,
            "",
            "=== HARD-BANNED SLOP CLICHES (INSTANT REJECTION) ===",
            "Do NOT use any of the following cliché phrases: 'baritone trombone', 'trombone glissando',",
            "'contrabass drone', 'slurping death-rattle', 'pneumatic', 'hydraulic', 'fatal tactical error',",
            "'gives up the ghost', 'ringing silence', 'displacement of mass', 'small-caliber gunfire'.",
            "",
            "=== SYNTHESIS INSTRUCTION ===",
            f"Synthesize the complete scene from scratch through the authentic voice of {self.lens.name}.",
            "Stage every physical reaction, vanity, and character embarrassment with unvarnished sensory detail.",
            "Embed all dialogue lines in exact order with speaker cues and parentheticals.",
            "Output ONLY the final formatted scene text."
        ])
        return "\n".join(prompt_lines)

    def validate_candidate(
        self,
        skeleton: Sequence[DialogueLine],
        candidate_text: str,
        *,
        require_order: bool = False,
        critic: Optional[SlopCritic] = None,
        packet: Optional[Any] = None,
        infill_plan: Optional[Any] = None,
        source_edit: Optional[Tuple[int, int]] = None,
        mind_projections: Optional[Sequence[Any]] = None,
    ) -> Tuple[bool, List[str]]:
        issues: List[str] = []
        # 1. Dialogue Invariant Gate
        ok_dialogue, missing_lines = verify_dialogue_invariant(skeleton, candidate_text, require_order=require_order)
        if not ok_dialogue:
            issues.append(f"dialogue drift: missing {len(missing_lines)} lines ({missing_lines[0]})")

        # 2. Cliché Blacklist & SlopCritic Gate
        cliches = blacklisted_cliches(candidate_text)
        if cliches:
            issues.append("blacklisted clichés: " + ", ".join(cliches[:2]))
        active_critic = critic
        if active_critic is not None:
            crit = active_critic.critique(candidate_text)
            for blk in crit.hard_blocks:
                if blk not in issues and not blk.startswith("Blacklisted AI cliche"):
                    issues.append(blk)

        # 3. Optional Neurosymbolic Pipeline / Seam / MindProjection Gates
        if packet is not None:
            from ..scoped_pipeline import validate_output
            for msg in validate_output(packet, candidate_text, source_edit=source_edit):
                if msg not in issues:
                    issues.append(msg)
        if infill_plan is not None:
            from ..slot_infill import validate_infill_seams
            seam_rep = validate_infill_seams(infill_plan, candidate_text, source_edit=source_edit)
            for msg in seam_rep.issues:
                if msg not in issues:
                    issues.append(msg)
        if mind_projections is not None:
            from story_graph.mind_resolver import check_interaction_rules
            for msg in check_interaction_rules(candidate_text, mind_projections):
                if msg not in issues:
                    issues.append(msg)

        return len(issues) == 0, issues

    def synthesize_best_of_n(
        self,
        provider: Any,
        scene_heading: str,
        beats: Sequence[DramaticBeat | str],
        skeleton: Sequence[DialogueLine] = (),
        *,
        n: int = 4,
        reference_text: str = "",
        evaluator: Optional[Any] = None,
        style_model: Optional[Any] = None,
        margin: float = 0.03,
        min_score: float = 0.0,
        require_order: bool = True,
        viewpoint: Optional[str] = None,
        world_laws: Sequence[str] = (),
        mind_directives: Sequence[str] = (),
        epistemic_withheld: Sequence[str] = (),
        craft_cues: Sequence[str] = (),
        max_bytes: int = MAX_CRAFT_BRIEF_BYTES,
        packet: Optional[Any] = None,
        infill_plan: Optional[Any] = None,
        mind_projections: Optional[Sequence[Any]] = None,
        request: Optional[Any] = None,
        seeds: Optional[Sequence[int]] = None,
    ) -> Dict[str, Any]:
        """Generate up to n candidates from a <6 KB CraftBrief, filter neurosymbolically, and rank via BestOfN + SlopCritic."""
        from ..guards import token_overlap
        from ..styleprint import distance, fingerprint

        brief = self.compile_brief(
            scene_heading,
            beats,
            skeleton,
            viewpoint=viewpoint,
            world_laws=world_laws,
            mind_directives=mind_directives,
            epistemic_withheld=epistemic_withheld,
            craft_cues=craft_cues,
            max_bytes=max_bytes,
            seed=seeds[0] if seeds else None,
        )
        raw_req = request if request is not None else type("BriefRequest", (), {"original_text": reference_text or "\n".join(str(b) for b in beats)})()

        accepted: List[Candidate] = []
        rejected: List[Dict[str, Any]] = []
        critiques: List[Dict[str, Any]] = []

        for idx in range(max(1, int(n))):
            prompt_idx = brief.prompt
            if seeds and idx < len(seeds) and idx > 0:
                prompt_idx = self.compile_brief(
                    scene_heading,
                    beats,
                    skeleton,
                    viewpoint=viewpoint,
                    world_laws=world_laws,
                    mind_directives=mind_directives,
                    epistemic_withheld=epistemic_withheld,
                    craft_cues=craft_cues,
                    max_bytes=max_bytes,
                    seed=seeds[idx],
                ).prompt
            if callable(provider):
                candidate_text = provider(prompt_idx)
            else:
                candidate_text = provider.generate_rewrite(raw_req, prompt_idx)

            if not isinstance(candidate_text, str) or not candidate_text.strip():
                rejected.append({"index": idx, "issues": ["Empty candidate"], "text": ""})
                continue

            crit = self.critic.critique(candidate_text)
            ok, issues = self.validate_candidate(
                skeleton,
                candidate_text,
                require_order=require_order,
                critic=self.critic,
                packet=packet,
                infill_plan=infill_plan,
                mind_projections=mind_projections,
            )
            critiques.append({"index": idx, **crit.to_dict(), "accepted": ok, "issues": list(issues)})
            if not ok:
                rejected.append({"index": idx, "issues": list(issues), "text": candidate_text, "slop_score": crit.slop_score})
                continue

            overlap = token_overlap(reference_text, candidate_text) if reference_text else 0.0
            style_dist = distance(fingerprint(candidate_text), style_model) if style_model else 0.0
            sim = float(evaluator.similarity(candidate_text)) if evaluator is not None else 0.5
            cand = score_text(
                candidate_text,
                similarity=sim,
                style=style_dist,
                overlap=overlap,
                slop_quality=crit.quality_bonus,
                slop_score=crit.slop_score,
                slop_weight=0.30,
            )
            cand.parts["index"] = float(idx)
            accepted.append(cand)

        winner = select_best(accepted, margin=margin, min_score=min_score) if accepted else None
        alternatives = select_all_best(accepted, margin=margin, min_score=min_score) if accepted else []
        ranked = sorted(accepted, key=lambda c: c.score, reverse=True)
        return {
            "status": "PROPOSED" if winner is not None else "BLOCKED",
            "winner": {"text": winner.text, "score": winner.score, "parts": winner.parts} if winner else None,
            "alternatives": [{"text": c.text, "score": c.score, "parts": c.parts} for c in alternatives],
            "candidates": [{"text": c.text, "score": c.score, "parts": c.parts} for c in ranked],
            "rejected": rejected,
            "critic_reports": critiques,
            "brief": brief.to_dict(),
            "issues": [] if winner is not None else ([r["issues"][0] for r in rejected if r["issues"]] or ["No candidate passed"]),
        }
