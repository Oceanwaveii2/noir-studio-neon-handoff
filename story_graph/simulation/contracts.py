"""Pydantic v2 Stage 1 (Emergent Simulation) -> Stage 2 (Masked Rendering) contracts.

Architectural boundary: this module lives strictly inside `story_graph` and must never
import `prose_engine` or `tools`. Model/LLM execution is injected via `SimulationModelPort`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from story_graph.canon_models import StoryCoord

CanonMode = Literal["canon", "non_canon", "alternate_canon", "time_travel_canon"]
PinRole = Literal["personality_mind", "catalyst_trigger", "rhythm_timing", "relationship_chemistry"]
UpliftPct = Literal[0, 25, 50, 75, 100]
CacheStatus = Literal["CACHE_HIT", "RECOMPUTED"]

_REQUIRED_STANCE_SCALARS = ("trust", "patience", "affection", "comedic_friction")

_TIER_DEFAULTS: Dict[int, Dict[str, Any]] = {
    0: {"min_token_divergence": 0.0, "max_token_divergence": 0.0, "style_ref_count": 0, "temperature": 0.0},
    25: {"min_token_divergence": 0.05, "max_token_divergence": 0.25, "style_ref_count": 2, "temperature": 0.45},
    50: {"min_token_divergence": 0.20, "max_token_divergence": 0.55, "style_ref_count": 4, "temperature": 0.72},
    75: {"min_token_divergence": 0.45, "max_token_divergence": 0.80, "style_ref_count": 6, "temperature": 0.88},
    100: {"min_token_divergence": 0.65, "max_token_divergence": 1.0, "style_ref_count": 8, "temperature": 0.98},
}


class TypedMediaPin(BaseModel):
    """Multimodal asset pinned to a character form, story beat, or directed relationship edge."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    sha256: str
    pin_role: PinRole
    stage_a_track_ref: str
    bridging_stage_direction: str = ""

    @field_validator("asset_id", "sha256", "stage_a_track_ref")
    @classmethod
    def _non_empty_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field must be a non-empty string")
        return cleaned

    @model_validator(mode="after")
    def _validate_catalyst_bridge(self) -> "TypedMediaPin":
        if self.pin_role == "catalyst_trigger" and not self.bridging_stage_direction.strip():
            raise ValueError("catalyst_trigger media pins require a non-empty bridging_stage_direction")
        return self


class DirectedRelationshipEdge(BaseModel):
    """Variant-specific, directional relationship edge inside the Character Relationships Controller."""

    model_config = ConfigDict(extra="forbid")

    edge_id: str
    universe_id: str
    source_character_id: str
    source_form_id: str
    target_character_id: str
    target_form_id: str
    inherits_from: Optional[str] = None
    scope_branch: str = "main"
    from_episode_pos: float = 0.0
    directional_stance: Dict[str, Any]
    stage_directions: List[str] = Field(default_factory=list)
    media_pins: List[TypedMediaPin] = Field(default_factory=list)
    authority: str = "author_override"

    @field_validator(
        "edge_id",
        "universe_id",
        "source_character_id",
        "source_form_id",
        "target_character_id",
        "target_form_id",
        "scope_branch",
        "authority",
    )
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Identifier field must be non-empty")
        return cleaned

    @field_validator("directional_stance")
    @classmethod
    def _validate_directional_stance(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        for key in _REQUIRED_STANCE_SCALARS:
            if key not in value:
                raise ValueError(f"directional_stance missing required scalar '{key}'")
            num = value[key]
            if isinstance(num, bool) or not isinstance(num, (int, float)) or not (0.0 <= float(num) <= 1.0):
                raise ValueError(f"directional_stance['{key}'] must be a number in [0.0, 1.0]")
        perception = value.get("subjective_perception")
        if not isinstance(perception, str) or not perception.strip():
            raise ValueError("directional_stance['subjective_perception'] must be a non-empty string")
        return value


class AgentIntentProposal(BaseModel):
    """Structured character-agent action proposal posted to the shared BeatBlackboard."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    character_id: str
    form_id: str
    epistemic_snapshot_digest: str
    goal: str
    speech_act: str
    target_id: Optional[str] = None
    proposed_action: str
    intensity: float = Field(ge=0.0, le=1.0)

    @field_validator("agent_id", "character_id", "form_id", "epistemic_snapshot_digest", "goal", "speech_act", "proposed_action")
    @classmethod
    def _non_empty_proposal_field(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Proposal text fields must be non-empty")
        return cleaned


class BeatBlackboard(BaseModel):
    """Concordia-style shared workspace for Stage 1 multi-agent beat simulation."""

    model_config = ConfigDict(extra="forbid")

    coord: StoryCoord
    world_state_digest: str
    active_forms: Dict[str, str] = Field(default_factory=dict)
    active_relationships: List[DirectedRelationshipEdge] = Field(default_factory=list)
    stage_b_practices: List[Dict[str, Any]] = Field(default_factory=list)
    proposals: List[AgentIntentProposal] = Field(default_factory=list)
    arbitration_decisions: List[Dict[str, Any]] = Field(default_factory=list)
    blocked_law_violations: List[Dict[str, Any]] = Field(default_factory=list)


class UpliftSlotPolicy(BaseModel):
    """DLSS-5-style per-span uplift/freeze sampling and divergence policy for Stage 2 rendering."""

    model_config = ConfigDict(extra="forbid")

    slot_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    uplift_pct: UpliftPct
    max_token_divergence: float = Field(ge=0.0, le=1.0)
    min_token_divergence: float = Field(ge=0.0, le=1.0)
    style_ref_count: int = Field(ge=0)
    temperature: float = Field(ge=0.0, le=2.0)

    @field_validator("slot_id")
    @classmethod
    def _non_empty_slot(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("slot_id must be non-empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_bounds_and_hard_lock(self) -> "UpliftSlotPolicy":
        if self.end <= self.start:
            raise ValueError("Slot end offset must be strictly greater than start offset")
        if self.min_token_divergence > self.max_token_divergence:
            raise ValueError("min_token_divergence cannot exceed max_token_divergence")
        if self.uplift_pct == 0:
            if self.max_token_divergence != 0.0 or self.min_token_divergence != 0.0:
                raise ValueError("Hard lock (uplift_pct=0) requires min/max_token_divergence == 0.0")
            if self.temperature != 0.0:
                raise ValueError("Hard lock (uplift_pct=0) requires temperature == 0.0")
        return self

    @classmethod
    def for_tier(cls, slot_id: str, start: int, end: int, uplift_pct: UpliftPct) -> "UpliftSlotPolicy":
        preset = _TIER_DEFAULTS[uplift_pct]
        return cls(
            slot_id=slot_id,
            start=start,
            end=end,
            uplift_pct=uplift_pct,
            **preset,
        )


class BeatDiscoursePlan(BaseModel):
    """Stage 1 simulation output handed to Stage 2 Masked Sequential Prose Renderer."""

    model_config = ConfigDict(extra="forbid")

    beat_id: str
    pdg_input_hash: str
    cache_status: CacheStatus
    locked_anchors: List[Dict[str, Any]] = Field(default_factory=list)
    slot_policies: List[UpliftSlotPolicy] = Field(default_factory=list)
    emergent_beats: List[Dict[str, Any]] = Field(default_factory=list)
    delta_receipts: List[Dict[str, Any]] = Field(default_factory=list)
    collision_trace: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator("beat_id", "pdg_input_hash")
    @classmethod
    def _non_empty_plan_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("beat_id and pdg_input_hash must be non-empty")
        return cleaned


class CausalTemporalBridge(BaseModel):
    """Scoped cross-episode memory/causal bridge for Time-Travel Canon arcs."""

    model_config = ConfigDict(extra="forbid")

    bridge_id: str
    origin_branch: str
    origin_pos: float
    origin_beat: int = Field(ge=0)
    target_branch: str
    target_pos: float
    target_beat: int = Field(ge=0)
    carrier_character_id: str
    carried_memory_ids: List[str] = Field(default_factory=list)

    @field_validator("bridge_id", "origin_branch", "target_branch", "carrier_character_id")
    @classmethod
    def _require_non_empty_bridge_field(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Bridge identifiers and carrier_character_id must be non-empty")
        return cleaned


@runtime_checkable
class SimulationModelPort(Protocol):
    """Port implemented by prose_engine adapters so story_graph stays dependency-free."""

    def propose_intent(
        self,
        blackboard: BeatBlackboard,
        character_id: str,
        form_id: str,
    ) -> AgentIntentProposal:
        """Generate one character/form agent's structured intent proposal from its B_t view."""
        ...

    def arbitrate_blackboard(self, blackboard: BeatBlackboard) -> BeatDiscoursePlan:
        """Resolve colliding proposals against World Laws and emit a BeatDiscoursePlan."""
        ...
