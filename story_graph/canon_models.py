"""Domain models for accumulative universe laws, character minds, and timeline state deltas."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

ASSERTION_CLASSES = (
    "narration_fact",
    "stage_direction",
    "dialogue_literal_claim",
    "dialogue_teasing",
    "character_belief",
    "show_quote",
    "negated_divergence",
)

LAW_MODALITIES = ("hard_invariant", "soft_tendency", "import_bleed_guard")

EXCEPTION_POLICIES = (
    "forbidden",
    "requires_character_trait",
    "quote_or_negation_exempt",
)

DELTA_OPS = (
    "SET_RELATIONSHIP",
    "SET_RELATIONSHIP_FACET",
    "RETRACT_RELATIONSHIP",
    "SET_BIOLOGY_STAGE",
    "SET_ATTRACTION_PROFILE",
    "GRANT_DEVICE",
    "BIND_ALTER_IDENTITY",
    "SET_MEMORY",
    "REVEAL_FORM",
    "GRANT_KNOWLEDGE",
)


@dataclass(frozen=True)
class StoryCoord:
    """Exact temporal and branch coordinate in a story timeline."""

    universe_id: str
    branch: str
    episode_id: str
    episode_position: float
    beat: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UniverseLawV2:
    """Modality- and scope-typed universe-level constraint."""

    law_id: str
    universe_id: str
    name: str
    statement: str
    modality: str
    exception_policy: str
    assertion_scope: Tuple[str, ...]
    rule_kind: str = "constraint"
    pattern: Optional[str] = None
    negation_cues: Tuple[str, ...] = field(default_factory=tuple)
    allow_context: Tuple[str, ...] = field(default_factory=tuple)
    branch: str = "*"
    valid_from: Optional[Tuple[float, int]] = None
    valid_until: Optional[Tuple[float, int]] = None
    enabled: bool = True
    source_id: str = "afm-canon"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CharacterMind:
    """Stable identity, household link, and genetic inheritance disposition for one character."""

    character_id: str
    universe_id: str
    canonical_name: str
    family_id: Optional[str] = None
    default_surname: str = ""
    species_baseline: str = "human"
    home_location: str = ""
    aliases: Tuple[str, ...] = field(default_factory=tuple)
    inheritance_model: Dict[str, Any] = field(default_factory=dict)
    baseline_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CharacterTrait:
    """Character-local trait or soft-law exception grant (for example, Noir's exception)."""

    trait_id: str
    universe_id: str
    owner_id: str
    trait_kind: str
    predicate: str
    value: Any
    grants_law_exception_id: Optional[str] = None
    evidence_summary: str = ""
    active_from_branch: str = "*"
    active_from_pos: Optional[float] = None
    active_from_beat: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CharacterMemory:
    """Character-local, family-shared, or viewpoint-isolated episodic memory/belief."""

    memory_id: str
    universe_id: str
    owner_scope: str  # 'personal' | 'family' | 'shared'
    owner_id: str
    subject_id: str
    predicate: str
    object_value: str
    truth_status: str = "established_fact"  # established_fact | false_belief | tease_joke | retconned_assumption
    branch: str = "main"
    episode_pos: float = 0.0
    beat: int = 0
    source_event_id: str = "seed"
    revision: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StateDelta:
    """Append-only event-sourced state transition ordered along (branch, episode_pos, beat, seq)."""

    delta_id: str
    universe_id: str
    branch: str
    episode_id: str
    episode_pos: float
    beat: int
    seq: int
    op: str
    subject_id: str
    target_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    source_event_id: Optional[str] = None
    authority: str = "canon_timeline"
    revision: int = 1
    retired: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateClaim:
    """Structured claim extracted from manuscript prose or dialogue with assertion metadata."""

    claim_id: str
    coord: StoryCoord
    block_id: str
    span_start: int
    span_end: int
    excerpt: str
    assertion_class: str
    subject_id: str
    predicate: str
    value_or_target: str
    speaker_id: Optional[str] = None
    confidence: float = 1.0
    extractor: str = "deterministic"
    source_origin: str = "author_manuscript"
    suggested_delta: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationFinding:
    """Diagnostic produced by validating claims or text against a CompiledWorldState."""

    status: str  # 'supported' | 'conflict' | 'warning' | 'advisory' | 'uncertain'
    severity: str  # 'info' | 'warning' | 'error'
    code: str
    rule_id: str
    reason: str
    evidence: str
    assertion_class: str = "narration_fact"
    subject_id: Optional[str] = None
    span_start: Optional[int] = None
    span_end: Optional[int] = None
    provenance: str = ""
    quick_actions: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompiledWorldState:
    """Materialized cumulative state for one coordinate along inherited branch ancestry."""

    coord: StoryCoord
    viewpoint: Optional[str]
    hard_invariants: Tuple[UniverseLawV2, ...]
    soft_tendencies: Tuple[UniverseLawV2, ...]
    import_bleed_guards: Tuple[UniverseLawV2, ...]
    characters: Dict[str, Dict[str, Any]]
    relationships: Dict[Tuple[str, str], Dict[str, Any]]
    memories: Tuple[CharacterMemory, ...]
    hidden_facts: Tuple[Dict[str, Any], ...]
    applied_deltas: Tuple[str, ...]
    state_digest: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "coord": self.coord.to_dict(),
            "viewpoint": self.viewpoint,
            "hard_invariants": [law.to_dict() for law in self.hard_invariants],
            "soft_tendencies": [law.to_dict() for law in self.soft_tendencies],
            "import_bleed_guards": [law.to_dict() for law in self.import_bleed_guards],
            "characters": self.characters,
            "relationships": {f"{a}->{b}": v for (a, b), v in self.relationships.items()},
            "memories": [m.to_dict() for m in self.memories],
            "hidden_facts": list(self.hidden_facts),
            "applied_deltas": list(self.applied_deltas),
            "state_digest": self.state_digest,
        }
