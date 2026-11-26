"""
Variation engine: different takes, not reworded versions of one take.

Sampling the same prompt gives near-identical drafts (62-86% token overlap in practice). So the
variation is driven by *treatments*: distinct causes, beat orders and registers for the same
fact set. Each treatment gets its own draft; duplicates are filtered by cross-variant overlap;
stockness is scored with the tell profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

TREATMENTS = {
    "nanite_malfunction": "The change is a nanite malfunction: the machines obey a wrong command.",
    "wish_gone_wrong": "The change is a wish that lands literally and badly.",
    "curse": "The change is a curse from someone present, said out loud.",
    "medical": "The change is a clinic procedure with side effects.",
    "dream": "The change is a dream that refuses to end.",
    "staged": "The change is being staged for a camera, and everyone knows it.",
    "inheritance": "The change is inherited: her mother's body arriving early.",
}


@dataclass
class Variant:
    treatment: str
    text: str
    facts_ok: bool = True
    missing: List[str] = field(default_factory=list)
    tell_density: float = 0.0
    overlap_original: float = 0.0
    max_overlap_other: float = 0.0
    accepted: bool = False
    reason: str = ""


def prompt_for(
    original_facts: Sequence[str],
    treatment: str,
    voice_card: str = "",
    forbidden: Sequence[str] = (),
    events: Sequence[str] = (),
    tone: str = "",
    exemplars: Sequence[str] = (),
    references: Sequence[str] = (),
    context: str = "",
) -> str:
    direction = TREATMENTS.get(treatment, treatment)
    parts = [
        "MUST KEEP EXACTLY (names, numbers, quoted lines): " + ", ".join(original_facts),
    ]
    if events:
        parts.append("EVENTS (all must happen, in any order you can justify): " + " | ".join(events))
    parts += [
        "TREATMENT: " + direction,
        "Write the beat anew from the facts. Same events, different route: change the cause, the "
        "order of escalation, and the register. Do not reuse the original's comparisons.",
        "STAGE, DO NOT ENUMERATE: put at most three events on the page, dramatized; imply the "
        "rest. Never list the facts one sentence at a time. Let the treatment change which "
        "moment is on the page and how badly it escalates.",
        "Never begin a sentence with 'So'. Do not summarise; stay inside the scene.",
    ]
    if forbidden:
        parts.append("FORBIDDEN IMAGES: " + ", ".join(forbidden))
    if tone:
        parts.append("TONE: " + tone)
    if exemplars:
        parts.append("REGISTER EXAMPLES from this scene (match the voice, not the content):\n" + "\n".join(exemplars))
    if references:
        parts.append(
            "VOICE REFERENCES from the reference books (actively draw upon their rhythm, diction, "
            "idioms, and sentence shapes):\n"
            + "\n".join(f"- {reference}" for reference in references)
        )
    if context:
        parts.append(context)
    if voice_card:
        parts.append(voice_card)
    parts.append("Return only the paragraph.")
    return "\n\n".join(parts)


class VariationSet:
    def __init__(self, max_pair_overlap: float = 0.55, max_original_overlap: float = 0.45):
        self.max_pair_overlap = max_pair_overlap
        self.max_original_overlap = max_original_overlap

    def run(
        self,
        provider,
        request,
        original: str,
        facts: Sequence[str],
        treatments: Sequence[str],
        voice_card: str = "",
        forbidden: Sequence[str] = (),
        tell_profile: Optional[dict] = None,
        events: Sequence[str] = (),
        tone: str = "",
        exemplars: Sequence[str] = (),
        references: Sequence[str] = (),
        context: str = "",
        world=None,
        house=None,
    ) -> List[Variant]:
        from ..guards import token_overlap
        from .tellgate import score as tell_score

        variants: List[Variant] = []
        for treatment in treatments:
            prompt = prompt_for(
                facts, treatment, voice_card, forbidden, events, tone, exemplars, references, context
            )
            try:
                text = provider.generate_rewrite(request, prompt)
            except Exception:
                continue
            text = (text or "").strip()
            if not text:
                continue
            variant = Variant(treatment=treatment, text=text)
            variant.overlap_original = token_overlap(original, text)
            if tell_profile:
                variant.tell_density = tell_score(text, tell_profile).density

            missing = [fact for fact in facts if fact.lower() not in text.lower()]
            variant.missing = missing
            variant.facts_ok = not missing

            if world is not None and (world.violations(text) or world.plausibility(text)):
                breaks = world.violations(text) + world.plausibility(text)
                variant.reason = "breaks world state: " + "; ".join(f"{p} ({w})" for p, w in breaks[:2])
            elif house is not None and house.check_scene([text]):
                variant.reason = "staging: " + "; ".join(house.check_scene([text])[:2])
            elif variant.overlap_original > self.max_original_overlap:
                variant.reason = f"too close to the original ({variant.overlap_original:.2f})"
            elif not variant.facts_ok:
                variant.reason = "drops facts: " + ", ".join(missing[:3])
            else:
                variant.max_overlap_other = max(
                    (token_overlap(other.text, text) for other in variants if other.accepted),
                    default=0.0,
                )
                if variant.max_overlap_other > self.max_pair_overlap:
                    variant.reason = f"too similar to an earlier variant ({variant.max_overlap_other:.2f})"
                else:
                    variant.accepted = True
                    variant.reason = "ok"
            variants.append(variant)
        return variants
