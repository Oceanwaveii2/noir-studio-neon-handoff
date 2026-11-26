"""
Rewrite strength presets for the prose conditioner.

light     smallest change that clears the flagged issue
standard  rewrite the paragraph in place
rebuild   write the beat anew: no reuse of the original's sentences, heavier book influence

Each preset controls how many reference passages are retrieved, how close a candidate may stay
to the original (token overlap), the allowed length ratio, and the directive appended to the
prompt.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Strength:
    name: str
    references: int
    max_overlap: float
    min_ratio: float
    max_ratio: float
    directive: str


_EDIT = (
    "CONDITIONING DIRECTIVE: Rewrite the paragraph with authentic human voice. Keep every concrete fact, character, "
    "and action. Do not mirror robotic AI clause structures. Ground the scene in real sensory friction (smell, sound, "
    "texture, temperature). Keep dialogue and canon facts intact. Return only the rewritten paragraph."
)

_DYNAMIC_REWRITE = (
    "REWRITE DIRECTIVE: Rewrite this beat with bold human voice, asymmetric rhythm, and physical punch. "
    "Do not preserve the original's sentence structure or clause-by-clause symmetry; paraphrase is failure. "
    "Ban AI cliché stage business (no jaw-clenching, no wavering mirror reflections, no 'pressing two fingers to the stomach'). "
    "Ground the scene in tactile friction—pinching zippers, sweating mascara, chemical bleach, unforgiving daylight, "
    "or unglamorous bodily distress. Match the voice of the REFERENCE PASSAGES (Irby, Susann, Collins, Anderson, Lockwood). "
    "Keep all concrete character names, numbers, props, and inviolable dialogue 100% intact. "
    "Return only the rewritten paragraph."
)

_REBUILD = (
    "REBUILD DIRECTIVE: Write this beat anew from the facts and the reference passages. "
    "Do not reuse the original's sentences, openings, or clause structure. Restructure freely, compress or expand "
    "within the budget, and match the voice of the REFERENCE PASSAGES — their raw human rhythm, specific diction, "
    "and asymmetric sentence shapes. Banned: literary AI clichés (heat mirages, coiled springs, riots of texture, Stonehenges). "
    "Replace them with visceral physical facts and sharp, authentic domestic/glamour details. "
    "Keep every concrete character name, number, prop, and inviolable dialogue intact. Return only the rewritten paragraph."
)

PRESETS = {
    "light": Strength(
        name="light",
        references=2,
        max_overlap=0.75,
        min_ratio=0.5,
        max_ratio=1.5,
        directive=_EDIT,
    ),
    "standard": Strength(
        name="standard",
        references=4,
        max_overlap=0.55,
        min_ratio=0.4,
        max_ratio=2.0,
        directive=_DYNAMIC_REWRITE,
    ),
    "rebuild": Strength(
        name="rebuild",
        references=6,
        max_overlap=0.40,
        min_ratio=0.6,
        max_ratio=1.8,
        directive=_REBUILD,
    ),
}


def get(name: str) -> Strength:
    try:
        return PRESETS[name]
    except KeyError:
        raise ValueError(f"unknown strength {name!r}; choose {', '.join(PRESETS)}") from None
