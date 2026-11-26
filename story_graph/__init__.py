"""
Story Graph: Modular narrative state, causal dependency, and epistemic ledger system.
Decoupled from the Prose Engine.
"""

from .compiler import (
    BeatPacket,
    BeatPacketCompiler,
)
from .ontology import (
    AuraField,
    AuraType,
    KinshipRelation,
    MorphAvatar,
    MorphPermission,
    OntologyGraph,
    RelationshipType,
    ReproductionMode,
    SpeciesTrait,
    SpeciesType,
)
from .ontology_compiler import OntologyCompiler
from .future_heritage import (
    FUTURE_HERITAGE,
    HOT_SCOOMP_S18,
    HOT_SCOOMP_VARIANTS,
    FutureHeritage,
    FutureHeritageBeat,
    HotScoompVariant,
    future_heritage_ids,
    get_future_heritage,
    get_hot_scoomp_variant,
    hot_scoomp_variant_ids,
)
from .dag import (
    BeatNode,
    BeatSequencer,
    CausalDAG,
    CycleError,
    LocationPrecondition,
    PortalPrecondition,
    Precondition,
    SensoryPrecondition,
    SomaticPrecondition,
)
from .epistemic import (
    EpistemicLedger,
    Fact,
    KnowledgeEntry,
)
from .models import (
    CharacterState,
    Location,
    Portal,
    PortalState,
    Posture,
    PropState,
    Transaction,
    TransactionResult,
)
from .world_state import StoryWorldState

__all__ = [
    # Models
    "PortalState",
    "Posture",
    "Portal",
    "Location",
    "CharacterState",
    "PropState",
    "Transaction",
    "TransactionResult",
    "StoryWorldState",
    # DAG & Sequencing
    "CausalDAG",
    "BeatNode",
    "BeatSequencer",
    "CycleError",
    "Precondition",
    "LocationPrecondition",
    "PortalPrecondition",
    "SomaticPrecondition",
    "SensoryPrecondition",
    # Epistemic Ledger
    "Fact",
    "KnowledgeEntry",
    "EpistemicLedger",
    # Beat Packet Compiler
    "BeatPacket",
    "BeatPacketCompiler",
    # Biological Ontology & Invariant System
    "SpeciesType",
    "ReproductionMode",
    "RelationshipType",
    "MorphPermission",
    "AuraType",
    "SpeciesTrait",
    "KinshipRelation",
    "MorphAvatar",
    "AuraField",
    "OntologyGraph",
    "OntologyCompiler",
    # Future Heritage (planned, not active in the current story)
    "FutureHeritage",
    "FutureHeritageBeat",
    "FUTURE_HERITAGE",
    "HOT_SCOOMP_S18",
    "future_heritage_ids",
    "get_future_heritage",
    # Hot Scoomp versions
    "HotScoompVariant",
    "HOT_SCOOMP_VARIANTS",
    "get_hot_scoomp_variant",
    "hot_scoomp_variant_ids",
]
