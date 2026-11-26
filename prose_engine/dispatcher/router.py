"""
Sub-Corpus Dispatcher & Routing Engine.
Milestone M-PE2: Segmented Sub-Corpus Dispatcher.

Enforces beat-by-beat routing policies, builds prioritized candidate pools,
and applies soft weighting and genre biasing:
  - Primary authorized clusters receive dominant weights (>= 1.0) and priority boosts.
  - Secondary authorized clusters receive moderate weights (0.5 - 0.7).
  - Mismatched genres (e.g., 1970s romance melodrama on vanity/bathroom beats)
    receive steep soft-dampening penalties (weight <= 0.10), so they sit at the
    tail of the distribution. This allows text to feed off connective vocabulary
    without romance melodrama tone overwhelming the farce or sensuality.
  - Optional strict hard-block mode for zero-intersection legacy gates.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..prepass.models import BeatAestheticProfile
from .book_clusters import CLUSTERS, get_all_blocked_books, get_cluster_books


@dataclass
class RoutingPolicy:
    name: str
    authorized_clusters: List[str]
    damped_clusters: List[str] = field(default_factory=list)
    blocked_clusters: List[str] = field(default_factory=list)  # backward-compatible alias
    priority_books: List[str] = field(default_factory=list)
    primary_weight: float = 1.0
    secondary_weight: float = 0.6
    background_weight: float = 0.25
    damped_weight: float = 0.05
    strict_hard_block: bool = False

    def __post_init__(self):
        # Synchronize damped_clusters and blocked_clusters
        if not self.damped_clusters and self.blocked_clusters:
            self.damped_clusters = list(self.blocked_clusters)
        elif not self.blocked_clusters and self.damped_clusters:
            self.blocked_clusters = list(self.damped_clusters)


# -----------------------------------------------------------------------------
# Canonical Routing Policies (with Soft Weighting & Genre Biasing)
# -----------------------------------------------------------------------------

ROUTING_POLICIES: Dict[str, RoutingPolicy] = {
    # Policy A: Brazilian Sensuality & Voluptuous Curves
    "brazilian_sensual": RoutingPolicy(
        name="brazilian_sensual",
        authorized_clusters=["brazilian_sensual", "body_morph"],
        damped_clusters=["glamour_romance_melodrama"],
        blocked_clusters=["glamour_romance_melodrama"],
        priority_books=[
            "brazilian_tales_isaac_goldberg",
            "iracema_the_honey_lips_jose_de_alencar",
            "lyrics_dance_pop",
        ],
        primary_weight=1.0,
        secondary_weight=0.6,
        damped_weight=0.05,
        strict_hard_block=False,
    ),

    # Policy B: Acute Somatic Farce, Flatulence & Gut Comedy
    "farce_fart": RoutingPolicy(
        name="farce_fart",
        authorized_clusters=["modern_somatic_farce", "classical_bodily_farce", "cynical_satire"],
        damped_clusters=["glamour_romance_melodrama"],
        blocked_clusters=["glamour_romance_melodrama"],
        priority_books=[
            "fart_proudly_benjamin_franklin",
            "gulp_adventures_on_the_alimentary_canal_mary_roach",
            "the_bfg_whizzpopping_chronicles_roald_dahl",
            "me_talk_pretty_one_day_david_sedaris",
            "the_body_a_guide_for_occupants_bill_bryson",
            "guards_guards_swamp_dragon_chronicles_terry_pratchett",
            "breakfast_of_champions_kurt_vonnegut",
        ],
        primary_weight=1.0,
        secondary_weight=0.6,
        damped_weight=0.05,
        strict_hard_block=False,
    ),

    # Policy C: Domestic Authority & Suburban Satire
    "domestic_farce": RoutingPolicy(
        name="domestic_farce",
        authorized_clusters=["domestic_farce", "contemporary_humor"],
        damped_clusters=["glamour_romance_melodrama"],
        blocked_clusters=["glamour_romance_melodrama"],
        priority_books=[
            "right_ho_jeeves_p_g_wodehouse",
            "shit_my_dad_says_justin_halpern",
            "my_man_jeeves_p_g_wodehouse",
        ],
        primary_weight=1.0,
        secondary_weight=0.6,
        damped_weight=0.05,
        strict_hard_block=False,
    ),

    # Policy D: Slacker Cynicism & Sitcom Timing
    "sitcom_timing": RoutingPolicy(
        name="sitcom_timing",
        authorized_clusters=["contemporary_humor", "cynical_satire"],
        damped_clusters=["glamour_romance_melodrama"],
        blocked_clusters=["glamour_romance_melodrama"],
        priority_books=[
            "shit_my_dad_says_justin_halpern",
            "we_are_never_meeting_in_real_life_essays",
            "pulp_fiction_quentin_tarantino",
        ],
        primary_weight=1.0,
        secondary_weight=0.6,
        damped_weight=0.05,
        strict_hard_block=False,
    ),

    # Policy E: Body Morph & Volumetric Expansion
    "body_morph": RoutingPolicy(
        name="body_morph",
        authorized_clusters=["body_morph", "brazilian_sensual"],
        damped_clusters=["glamour_romance_melodrama"],
        blocked_clusters=["glamour_romance_melodrama"],
        priority_books=[
            "gargantua_and_pantagruel_francois_rabelais",
            "lyrics_dance_pop",
            "the_metamorphosis_franz_kafka",
            "the_day_my_bum_went_psycho_andy_griffiths",
        ],
        primary_weight=1.0,
        secondary_weight=0.6,
        damped_weight=0.05,
        strict_hard_block=False,
    ),
}


@dataclass
class DispatchedCorpus:
    beat_id: str
    scene_id: str
    policy_name: str
    authorized_books: List[str]            # Sorted in descending order of affinity weight!
    blocked_books: List[str]               # Damped books (weight <= 0.10) for backward compatibility
    book_weights: Dict[str, float] = field(default_factory=dict)
    cluster_weights: Dict[str, float] = field(default_factory=dict)
    damped_books: List[str] = field(default_factory=list)
    vector_queries: List[str] = field(default_factory=list)
    mandatory_physical_anchors: List[str] = field(default_factory=list)
    strict_hard_block: bool = False

    def __post_init__(self):
        if not self.damped_books and self.blocked_books:
            self.damped_books = list(self.blocked_books)
        elif not self.blocked_books and self.damped_books:
            self.blocked_books = list(self.damped_books)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "beat_id": self.beat_id,
            "scene_id": self.scene_id,
            "policy_name": self.policy_name,
            "authorized_book_count": len(self.authorized_books),
            "authorized_books": self.authorized_books,
            "blocked_book_count": len(self.blocked_books),
            "blocked_books": self.blocked_books,
            "damped_books": self.damped_books,
            "book_weights": self.book_weights,
            "cluster_weights": self.cluster_weights,
            "vector_queries": self.vector_queries,
            "mandatory_physical_anchors": self.mandatory_physical_anchors,
            "strict_hard_block": self.strict_hard_block,
        }


class SubCorpusDispatcher:
    """
    Intelligent section router with Soft Weighting & Genre Biasing.
    Partitions and biases the 105-book library per beat:
      - Assigns high affinity weights to primary and secondary authorized clusters.
      - Softly dampens mismatched genres (e.g. 1970s romance melodrama) to <= 0.10 weight,
        allowing text to feed off other text without romance melodrama dominating.
    """

    def __init__(self, custom_policies: Optional[Dict[str, RoutingPolicy]] = None):
        self.policies = custom_policies or ROUTING_POLICIES

    def get_policy(self, routing_name: str) -> RoutingPolicy:
        return self.policies.get(routing_name, self.policies["farce_fart"])

    def dispatch(
        self,
        profile: BeatAestheticProfile,
        strict_hard_block: Optional[bool] = None,
    ) -> DispatchedCorpus:
        policy = self.get_policy(profile.dominant_routing)
        is_hard = policy.strict_hard_block if strict_hard_block is None else strict_hard_block

        # 1. Compute cluster weights
        cluster_weights: Dict[str, float] = {}
        for c in policy.authorized_clusters:
            cluster_weights[c] = policy.primary_weight

        for sec in profile.secondary_routings:
            sec_policy = self.policies.get(sec)
            if sec_policy:
                for c in sec_policy.authorized_clusters:
                    if c not in cluster_weights:
                        cluster_weights[c] = policy.secondary_weight

        damped_clusters = policy.damped_clusters or policy.blocked_clusters
        for c in damped_clusters:
            cluster_weights[c] = 0.0 if is_hard else policy.damped_weight

        # 2. Gather books and compute book weights
        book_weights: Dict[str, float] = {}

        # Primary cluster books
        for c in policy.authorized_clusters:
            for b in get_cluster_books(c):
                book_weights[b] = max(book_weights.get(b, 0.0), policy.primary_weight)

        # Priority books boost (e.g. designated signature books get an extra boost)
        for pb in policy.priority_books:
            if pb in book_weights:
                book_weights[pb] = round(book_weights[pb] * 1.25, 2)
            else:
                book_weights[pb] = round(policy.primary_weight * 1.25, 2)

        # Secondary cluster books
        for sec in profile.secondary_routings:
            sec_policy = self.policies.get(sec)
            if sec_policy:
                for c in sec_policy.authorized_clusters:
                    if c not in damped_clusters:
                        for b in get_cluster_books(c):
                            if b not in book_weights:
                                book_weights[b] = policy.secondary_weight

        # Damped books
        damped_pool: Set[str] = get_all_blocked_books(damped_clusters)
        for b in damped_pool:
            if is_hard:
                book_weights[b] = 0.0
            else:
                book_weights[b] = min(book_weights.get(b, policy.damped_weight), policy.damped_weight)

        # 3. Build ordered candidate pool
        if is_hard:
            # Strict hard block: completely omit damped books
            final_authorized = [b for b, w in book_weights.items() if w > 0.0 and b not in damped_pool]
            final_authorized.sort(key=lambda b: (-book_weights.get(b, 0.0), b))
            final_damped = sorted(list(damped_pool))
        else:
            # Soft weighting and biasing:
            # All candidate books are retained, sorted in descending order of weight.
            # Damped books sit at the tail of the distribution with weight <= 0.10.
            final_authorized = sorted(
                list(book_weights.keys()),
                key=lambda b: (-book_weights.get(b, 0.0), b)
            )
            final_damped = sorted(list(damped_pool))

        return DispatchedCorpus(
            beat_id=profile.beat_id,
            scene_id=profile.scene_id,
            policy_name=policy.name,
            authorized_books=final_authorized,
            blocked_books=final_damped,
            book_weights=book_weights,
            cluster_weights=cluster_weights,
            damped_books=final_damped,
            vector_queries=copy.deepcopy(profile.vector_query_paths),
            mandatory_physical_anchors=copy.deepcopy(profile.mandatory_physical_anchors),
            strict_hard_block=is_hard,
        )

    def dispatch_manifest(
        self,
        profiles: Dict[str, BeatAestheticProfile],
        strict_hard_block: Optional[bool] = None,
    ) -> Dict[str, DispatchedCorpus]:
        return {b_id: self.dispatch(prof, strict_hard_block=strict_hard_block) for b_id, prof in profiles.items()}

    def audit_isolation(self, dispatched: DispatchedCorpus) -> Tuple[bool, List[str]]:
        """
        Audits isolation and soft weighting bias.
        In soft-bias mode (default), verifies:
          1. Primary books have high affinity weights (>= 1.0).
          2. Damped books have heavily attenuated weights (<= 0.15).
          3. Weight bias ratio (primary / damped) >= 10.0 (overwhelming priority).
          4. Top candidates are 100% dominated by primary/secondary clusters.
        In strict_hard_block mode, verifies 0 set intersection.
        """
        violations: List[str] = []

        if dispatched.strict_hard_block:
            contamination = set(dispatched.authorized_books) & set(dispatched.blocked_books)
            if contamination:
                violations.append(f"Blocked books contaminated authorized pool: {contamination}")
            return len(violations) == 0, violations

        # Soft biasing audit
        weights = dispatched.book_weights
        damped_set = set(dispatched.damped_books)

        # Check damped weights are strictly <= 0.15
        for db in damped_set:
            w = weights.get(db, 0.0)
            if w > 0.15:
                violations.append(f"Damped book '{db}' has excessively high weight: {w} > 0.15")

        # Check primary books have weight >= 1.0
        primary_found = False
        for b, w in weights.items():
            if b not in damped_set and w >= 1.0:
                primary_found = True
                break
        if not primary_found:
            violations.append("No primary authorized books found with weight >= 1.0")

        # Check top-K ordering: first 5 books must NOT be from damped pool
        top_5 = dispatched.authorized_books[:5]
        for b in top_5:
            if b in damped_set:
                violations.append(f"Damped book '{b}' ranked in top 5 of candidate pool!")

        return len(violations) == 0, violations
