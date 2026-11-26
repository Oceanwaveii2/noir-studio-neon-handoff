"""
story_graph/ontology.py
Core domain structures for Biological Ontology, Species Invariants, Kinship,
Morph Matrices, Dimensional Affordances, and Sensory/Aura Fields.
Milestone MO2 / Ontology-Wired Generative Systems.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from .future_heritage import FUTURE_HERITAGE


class SpeciesType(str, Enum):
    ALIEN_FOX_SIREN = "alien_fox_siren"
    HUMAN_DORMANT_FOX = "human_dormant_fox"
    HUMAN_STANDARD = "human_standard"


class ReproductionMode(str, Enum):
    NANOMACHINE_MONOSEXUAL = "nanomachine_monosexual"  # 100% female, zero male DNA, no father
    STANDARD_SEXUAL = "standard_sexual"


class RelationshipType(str, Enum):
    MARRIED_LESBIAN_COUPLE = "married_lesbian_couple"
    DATING_ON_BREAK = "dating_on_break"
    BOYFRIEND_GIRLFRIEND = "boyfriend_girlfriend"
    MOTHER_CHILD = "mother_child"
    SISTERS = "sisters"
    COLLEAGUES = "colleagues"


class MorphPermission(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class AuraType(str, Enum):
    YURI_FIELD_SIREN_PHEROMONE = "yuri_field_siren_pheromone"
    STANDARD_SCENT = "standard_scent"


@dataclass(frozen=True)
class SpeciesTrait:
    species_id: SpeciesType
    is_all_female_species: bool
    has_patriarchal_lineage: bool  # Strictly False for Alien Fox Sirens
    has_agelessness: bool          # Chronologically older, visually early 20s
    chronological_age: int
    visual_age_range: Tuple[int, int]
    reproduction_mode: ReproductionMode
    can_self_morph: bool
    can_target_morph: bool         # Can transform others
    default_seat_units_required: int = 1
    butt_span_chairs: float = 1.0


@dataclass
class MorphAvatar:
    avatar_id: str
    name: str
    trigger_type: str  # "intentional" or "involuntary_pelvic_pressure"
    visual_description: str
    somatic_tags: List[str] = field(default_factory=list)
    banned_pronouns: List[str] = field(default_factory=list)  # Stays female/she even in caricature


@dataclass
class KinshipRelation:
    subject_id: str
    target_id: str
    relation_type: RelationshipType
    notes: str = ""
    is_exclusive: bool = True
    forbid_terms: List[str] = field(default_factory=list)


@dataclass
class AuraField:
    field_id: str
    emitter_id: str
    aura_type: AuraType
    intensity: float = 1.0
    radius_hops: int = 2
    target_demographic: str = "straight_human_female"
    effect_description: str = (
        "Natural biological siren pheromones that heighten charisma and chemical allure, "
        "making sirens exceptionally appealing and magnetic to women, particularly very attractive, "
        "beautiful women, without forcing any decisions or actions."
    )


class OntologyGraph:
    """
    Formal Ontological Knowledge Graph & Active Invariant Ledger.
    Maintains universal world invariants, biological laws, and active constraints.
    """

    def __init__(self):
        self.species_registry: Dict[SpeciesType, SpeciesTrait] = {}
        self.character_species: Dict[str, SpeciesType] = {}
        self.character_morph_capabilities: Dict[str, Dict[str, bool]] = {}
        self.kinship_relations: List[KinshipRelation] = []
        self.morph_avatars: Dict[str, List[MorphAvatar]] = {}
        self.active_auras: Dict[str, AuraField] = {}
        self.dimensional_overrides: Dict[str, Dict[str, Any]] = {}
        self.hard_negative_rules: List[Dict[str, Any]] = []
        self.canon_divergences: List[Dict[str, str]] = []
        self.future_heritage: List[Dict[str, Any]] = []

    def get_character_morph_permissions(self) -> Dict[str, bool]:
        """Returns map of character_id -> bool whether they can shapeshift themselves."""
        if self.character_morph_capabilities:
            return {c: caps["can_self_morph"] for c, caps in self.character_morph_capabilities.items()}
        return {
            c: self.species_registry[s].can_self_morph
            for c, s in self.character_species.items()
            if s in self.species_registry
        }

    def can_character_target_morph(self, character_id: str) -> bool:
        """Returns True if character can transform others (e.g. Rainee via nanites)."""
        caps = self.character_morph_capabilities.get(character_id.lower())
        if caps:
            return caps.get("can_target_morph", False)
        species = self.character_species.get(character_id.lower())
        trait = self.species_registry.get(species) if species else None
        return trait.can_target_morph if trait else False

    @classmethod
    def create_canonical_foxy_mo2(cls) -> OntologyGraph:
        """Constructs the canonical ontology graph containing all 12 user rules."""
        onto = cls()

        # 1. Species Trait Definitions
        siren_trait = SpeciesTrait(
            species_id=SpeciesType.ALIEN_FOX_SIREN,
            is_all_female_species=True,
            has_patriarchal_lineage=False,
            has_agelessness=True,
            chronological_age=50,
            visual_age_range=(20, 24),
            reproduction_mode=ReproductionMode.NANOMACHINE_MONOSEXUAL,
            can_self_morph=True,
            can_target_morph=True,
            default_seat_units_required=2,
            butt_span_chairs=2.0,
        )
        onto.species_registry[SpeciesType.ALIEN_FOX_SIREN] = siren_trait

        haley_trait = SpeciesTrait(
            species_id=SpeciesType.HUMAN_DORMANT_FOX,
            is_all_female_species=False,
            has_patriarchal_lineage=False,  # Born of Francine & Rainee via nanites, NO father
            has_agelessness=False,
            chronological_age=23,
            visual_age_range=(22, 24),
            reproduction_mode=ReproductionMode.STANDARD_SEXUAL,
            can_self_morph=False,           # Haley CANNOT shapeshift
            can_target_morph=False,
            default_seat_units_required=1,
            butt_span_chairs=1.0,
        )
        onto.species_registry[SpeciesType.HUMAN_DORMANT_FOX] = haley_trait

        human_trait = SpeciesTrait(
            species_id=SpeciesType.HUMAN_STANDARD,
            is_all_female_species=False,
            has_patriarchal_lineage=True,
            has_agelessness=False,
            chronological_age=42,
            visual_age_range=(38, 44),
            reproduction_mode=ReproductionMode.STANDARD_SEXUAL,
            can_self_morph=False,
            can_target_morph=False,
            default_seat_units_required=1,
            butt_span_chairs=1.0,
        )
        onto.species_registry[SpeciesType.HUMAN_STANDARD] = human_trait

        # Assign character species and individual morph capabilities
        onto.character_species["rainee"] = SpeciesType.ALIEN_FOX_SIREN
        onto.character_species["stella"] = SpeciesType.ALIEN_FOX_SIREN
        onto.character_species["haley"] = SpeciesType.HUMAN_DORMANT_FOX
        onto.character_species["francine"] = SpeciesType.HUMAN_STANDARD

        onto.character_morph_capabilities = {
            "rainee": {"can_self_morph": True, "can_target_morph": True},
            "stella": {"can_self_morph": True, "can_target_morph": False},
            "haley": {"can_self_morph": False, "can_target_morph": False},
            "francine": {"can_self_morph": False, "can_target_morph": False},
        }

        # 2. Kinship & Lineage Ledger
        onto.kinship_relations.extend([
            KinshipRelation(
                subject_id="francine",
                target_id="rainee",
                relation_type=RelationshipType.MARRIED_LESBIAN_COUPLE,
                notes="Francine and Rainee are a married lesbian couple with children together via nanomachine reproduction.",
                forbid_terms=["husband", "Stan married", "father", "Dad", "stepdad", "heterosexual"]
            ),
            KinshipRelation(
                subject_id="rainee",
                target_id="francine",
                relation_type=RelationshipType.MARRIED_LESBIAN_COUPLE,
                notes="Rainee and Francine had sex and had kids via nanomachines. Stan is the ex who dumped Francine; he is not a husband and not part of the household. NO father, NO paternal lineage.",
                forbid_terms=["husband", "father", "Dad", "paternal", "male lineage"]
            ),
            KinshipRelation(
                subject_id="haley",
                target_id="jeff",
                relation_type=RelationshipType.BOYFRIEND_GIRLFRIEND,
                notes=(
                    "In the Spring Break-Up (S04E16) epoch, Haley is mostly human with dormant fox genetics "
                    "(heterosexual, no father, genetic machinery destined to awaken later) and dating her "
                    "boyfriend Jeff (not husband yet in Spring Break). Per inherited American Dad! timeline "
                    "progression, she marries Jeff later prior to Hot Scoomp (S18), loses attraction and is "
                    "physically repulsed by him on full fox awakening, cheats with Holly Graham, and later "
                    "salvages the marriage in Tapped Out via a Jeff-to-Jess transformation device."
                ),
                forbid_terms=["husband Jeff", "married to Jeff", "Jeff's wife", "Haley lesbian", "Haley siren"]
            ),
            KinshipRelation(
                subject_id="rainee",
                target_id="sisters",
                relation_type=RelationshipType.SISTERS,
                notes="Rainee has 3 alien sisters. Sororal lineage only; 100% all-female species.",
                forbid_terms=["brother", "father", "uncle", "grandfather", "patriarch"]
            )
        ])

        # 3. Morph Avatars
        onto.morph_avatars["rainee"] = [
            MorphAvatar(
                avatar_id="avatar_peter_griffin",
                name="Peter Griffin Variant",
                trigger_type="involuntary_pelvic_pressure",
                visual_description="Cleft butt-chin, bulbous nose, tight white crewneck, painted-on jeans over massive bubble rear",
                somatic_tags=["pelvic_relief", "comic_baritone", "spider_tattoo", "candy_canes"]
            ),
            MorphAvatar(
                avatar_id="avatar_hollywood_vixen",
                name="Glamour Auburn Vixen",
                trigger_type="intentional",
                visual_description="Lush Brazilian curves, four-foot auburn tail, peach silk kimono",
                somatic_tags=["gardenia_jasmine_perfume", "high_renaissance_bounce"]
            )
        ]

        # 4. Aura Fields (Yuri Field)
        onto.active_auras["rainee_yuri_field"] = AuraField(
            field_id="rainee_yuri_field",
            emitter_id="rainee",
            aura_type=AuraType.YURI_FIELD_SIREN_PHEROMONE,
            intensity=0.9,
            radius_hops=2,
            target_demographic="straight_human_female",
            effect_description=(
                "Natural biological siren pheromones that heighten chemical magnetism and charisma, "
                "making sirens exceptionally appealing and magnetic to women, particularly very attractive, "
                "beautiful women, without forcing any decisions or actions."
            )
        )

        # 5. Source-Show Divergences (World Lore)
        # The model imports American Dad! canon from the web. Record the divergence
        # explicitly so prompts and gates correct the import instead of enforcing it.
        onto.canon_divergences = [
            {
                "id": "divergence_ling_not_smith",
                "source_show": "American Dad!",
                "imported_canon": (
                    "Francine Smith, married to Stan Smith; Haley Smith; the Smith household."
                ),
                "story_canon": (
                    "Francine Ling never married Stan. Stan dumped her before any wedding, "
                    "so she kept the Ling name. The household is strictly Ling: Francine Ling, "
                    "Rainee Ling, Haley Ling, Stella Ling. Stan is a discarded ex, not a husband "
                    "and not a member of the household."
                ),
                "why": (
                    "Any web-derived 'Smith' surname, 'Mrs. Smith', 'Stan Smith', or "
                    "Stan-as-husband detail is an import error, not a permitted variant. "
                    "References to Stan as the man who dumped her are canon and allowed."
                ),
            }
        ]

        # 6. Universal Negative Invariants (Banned Hallucination Patterns)
        onto.hard_negative_rules = [
            {
                "id": "rule_no_patriarchs",
                "pattern": r"\b(?<!Francine's )(?<!Baba )father\b|\b(Dad|Daddy|patriarch|stepdad|step-dad)\b",
                "why": "Rainee belongs to an all-female alien fox species; Haley has two mothers via nanomachine reproduction. Zero male lineage or household fathers exist (Francine's adoptive father Baba Ling is permitted).",
                "allow_context": ["cartoon", "sitcom", "tv", "cosplay", "cosplaying"],
            },
            {
                "id": "rule_no_smith_surname",
                "pattern": (
                    r"\b(?:Stan(?:\s+Smith)?|(?:Mr|Mrs|Ms)\.?\s+Smith|the\s+Smiths?|"
                    r"Smith-Ling|Ling-Smith|(?:Haley|Francine|Rainee|Stella)\s+Smith|"
                    r"Smith(?:\s+(?:family|house|household|residence))?)\b"
                ),
                "why": (
                    "Source-show correction: American Dad! canon has Francine Smith married to "
                    "Stan Smith. In this story Francine never married Stan; he dumped her and she "
                    "kept the Ling name, so the household is strictly Ling. References to Stan as "
                    "the ex who dumped her are allowed; asserting a Smith surname or Stan as "
                    "husband is not."
                ),
                "allow_negated": True,
                "negation_cues": [
                    "never",
                    "didn't",
                    "did not",
                    "doesn't",
                    "does not",
                    "dumped",
                    "dumps",
                    "broke up",
                    "left her",
                    "her ex",
                    "ex-",
                    "former",
                    "maiden name",
                    "kept the ling name",
                    "instead of",
                    "rather than",
                    "before the wedding",
                ],
            },
            {
                "id": "rule_no_jeff_husband",
                "pattern": r"\b(husband\s+Jeff|Jeff\s+is\s+her\s+husband|Haley's\s+husband|married\s+to\s+Jeff)\b",
                "why": "Spring Break-Up (S04E16) epoch rule: Haley and Jeff are still dating as boyfriend/girlfriend here, prior to their later marriage (pre-Hot Scoomp).",
            },
            {
                "id": "rule_haley_dormant_fox_genes",
                "pattern": r"\bHaley\b[^.?!;]{0,60}\b(lesbian|siren|dating\s+a\s+girl|wife|married)\b",
                "why": "Spring Break-Up (S04E16) epoch rule: Haley is not a lesbian yet and not married in this episode; her fox genetic heritage is dormant and matures later across Hot Scoomp (after marrying Jeff) and Tapped Out.",
            },
            {
                "id": "rule_haley_no_morph",
                "pattern": r"\bHaley\b[^.?!;]{0,60}\b(shapeshifts?|morphs?|transformed?|flicks?\s+her\s+tail|pointed\s+ears|fur)\b",
                "why": "Haley is human with dormant genes and CANNOT shapeshift or manifest animal traits yet."
            },
            {
                "id": "rule_rainee_seating_capacity",
                "pattern": r"\bRainee\b[^.?!;]{0,60}\b(sits\s+comfortably\s+on\s+a\s+small\s+chair|slides\s+easily\s+into\s+a\s+single\s+seat)\b",
                "why": "Rainee's butt requires 2 chairs; seating her in a standard single seat without morphing/spanning 2 chairs violates physical invariants."
            }
        ]

        # 7. Future Heritage (planned, NOT active in this story)
        onto.future_heritage = [asdict(record) for record in FUTURE_HERITAGE.values()]

        return onto

    def get_summary_invariants(self) -> List[str]:
        """Returns concise positive rules for injection into prompt context."""
        return [
            "The family surname is strictly LING (Francine Ling, Rainee Ling, Haley Ling, Stella Ling). SOURCE-SHOW CORRECTION: American Dad! canon says 'Francine Smith' married to Stan Smith, but in this story Francine NEVER married Stan — he dumped her before any wedding — so she kept the Ling name. Any web-derived 'Smith' surname, 'Mrs. Smith', 'Stan Smith', or Stan-as-husband detail is an import error; references to Stan as the ex who dumped her are allowed.",
            "Francine and Rainee are a married lesbian couple. They had children together via nanomachine monosexual reproduction. Zero men, zero fathers in Rainee's species, and NO Stan involved in their family or conception (Stan is Francine's discarded ex who dumped her).",
            "Rainee is an alien from a 100% all-female species with NO patriarchal figures (no fathers, uncles, or grandfathers; all women). She has 3 alien sisters. (Francine is human; Francine's adoptive Chinese father is Baba Ling).",
            "Francine's adoptive parents are Baba Ling and Mama Ling. Baba Ling recently had inguinal hernia surgery, and Francine is going to his bedside to manually express his trapped abdominal post-op gas ('farting him' / 'ancestral farting').",
            "Rainee's species does not physically or visually age. Rainee is approximately 50 Earth years old, but perpetually appears in her early 20s.",
            "Rainee and Stella are Alien Fox Sirens. They emit biological siren pheromones (a 'Yuri Field') that operate like supercharged natural pheromones, heightening their charisma, chemical magnetism, and natural appeal to women, particularly very attractive, beautiful women, without forcing any decisions or actions.",
            "Rainee's backside and hips require 2 chairs of seating space (or custom double-wide commodes).",
            "Shapeshifting Matrix: Rainee can shapeshift herself and others (via nanites). Stella can shapeshift herself only. Haley's fox genetic heritage is strictly dormant and inactive in this episode; Haley CANNOT shapeshift. Rainee can assume multiple avatars both intentionally and spontaneously (e.g. Peter Griffin flatulent transformation).",
            "Haley is a human daughter whose alien fox genetic heritage is strictly DORMANT and NOT ACTIVE in this episode. She is NOT a lesbian yet; she is currently heterosexual and dating her boyfriend Jeff (not married; on-and-off break). Because her fox genes are dormant, she has NO animal traits (no ears, tail, or fur) and is living as a normal human woman dating a man. Rainee's roast that Haley 'inherited her boyfriend's flat white-boy ass' refers to boyfriend Jeff's flat rear end."
        ]
