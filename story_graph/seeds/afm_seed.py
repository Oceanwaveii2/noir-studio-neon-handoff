"""Seed canonical American Foxy Mom universe laws, character minds, traits, and accumulative deltas."""
from __future__ import annotations

import sqlite3

from story_graph.canon_models import (
    CharacterMemory,
    CharacterMind,
    CharacterTrait,
    StateDelta,
    UniverseLawV2,
)
from story_graph.state_compiler import (
    append_delta,
    ensure_canon_schema,
    grant_trait,
    record_memory,
    upsert_character_mind,
    upsert_law,
)

DEFAULT_AFM_UNIVERSE = "american-foxy-mom"


def seed_afm_universe(conn: sqlite3.Connection, *, universe_id: str = DEFAULT_AFM_UNIVERSE) -> None:
    """Populate idempotent Universe Laws, Character Minds, Traits, Memories, and State Deltas."""
    ensure_canon_schema(conn)
    _seed_laws(conn, universe_id)
    _seed_characters_and_traits(conn, universe_id)
    _seed_memories(conn, universe_id)
    _seed_timeline_deltas(conn, universe_id)


def _seed_laws(conn: sqlite3.Connection, universe_id: str) -> None:
    laws = (
        UniverseLawV2(
            law_id="fox_no_sons",
            universe_id=universe_id,
            name="Female-only alien fox lineage",
            statement="Hard biological rule: alien foxes cannot have biological sons.",
            modality="hard_invariant",
            exception_policy="forbidden",
            assertion_scope=("narration_fact", "stage_direction", "dialogue_literal_claim"),
            rule_kind="biology",
        ),
        UniverseLawV2(
            law_id="fox_female_siren_pheromones",
            universe_id=universe_id,
            name="Female-only siren pheromone emitter",
            statement="Only female fox lineages naturally carry siren pheromones.",
            modality="hard_invariant",
            exception_policy="forbidden",
            assertion_scope=("narration_fact", "stage_direction", "dialogue_literal_claim"),
            rule_kind="biology",
        ),
        UniverseLawV2(
            law_id="two_mom_nanomachinery",
            universe_id=universe_id,
            name="Two-mother nanomachinery conception",
            statement="Haley and Stella were conceived by Francine and Rainee via genetic nanomachinery with no biological father.",
            modality="hard_invariant",
            exception_policy="forbidden",
            assertion_scope=("narration_fact", "stage_direction", "dialogue_literal_claim"),
            rule_kind="parentage",
        ),
        UniverseLawV2(
            law_id="fox_sapphic_tendency",
            universe_id=universe_id,
            name="Fox siren female attraction tendency",
            statement="Foxes are strongly attracted to women via female-only siren pheromones and weakly/unattracted to men, though rare exceptions are biologically possible (for example Noir).",
            modality="soft_tendency",
            exception_policy="requires_character_trait",
            assertion_scope=("narration_fact", "stage_direction", "dialogue_literal_claim"),
            rule_kind="attraction",
        ),
        UniverseLawV2(
            law_id="import_guard_smith_stan",
            universe_id=universe_id,
            name="American Dad! Smith/Stan import bleed guard",
            statement="Household and surname are strictly Ling (Francine Ling never married Stan Smith), across all seasons; broadcast quotes and explicit negations are exempt.",
            modality="import_bleed_guard",
            exception_policy="quote_or_negation_exempt",
            assertion_scope=("narration_fact", "stage_direction", "dialogue_literal_claim"),
            rule_kind="import_guard",
            pattern=(
                r"\b(?:Stan(?:\s+Smith)?|(?:Mr|Mrs|Ms)\.?\s+Smith|the\s+Smiths?|"
                r"Smith-Ling|Ling-Smith|(?:Haley|Francine|Rainee|Stella)\s+Smith|"
                r"Smith\s+(?:family|house|household|residence|kitchen))\b"
            ),
            negation_cues=(
                "never", "didn't", "did not", "doesn't", "does not",
                "dumped", "ex-", "former", "kept the ling name", "instead of", "rather than",
            ),
        ),
    )
    for law in laws:
        upsert_law(conn, law)


def _seed_characters_and_traits(conn: sqlite3.Connection, universe_id: str) -> None:
    minds = (
        CharacterMind(
            character_id="francine",
            universe_id=universe_id,
            canonical_name="Francine Ling",
            family_id="ling",
            default_surname="Ling",
            species_baseline="human_standard",
            home_location="Ling House",
            aliases=("Frannie", "Mom"),
            inheritance_model={"adoptive_parents": ["Baba Ling", "Mama Ling"], "never_married_stan": True},
            baseline_notes="Married to Rainee Ling. Never married Stan Smith; retains Ling surname.",
        ),
        CharacterMind(
            character_id="rainee",
            universe_id=universe_id,
            canonical_name="Rainee Ling",
            family_id="ling",
            default_surname="Ling",
            species_baseline="alien_fox_siren",
            home_location="Ling House",
            aliases=("Mom 2", "Rainee Peter Griffen"),
            inheritance_model={"can_self_morph": True, "can_target_morph": True},
            baseline_notes="Alien fox siren married to Francine Ling; CIA case officer in Hot Scoomp.",
        ),
        CharacterMind(
            character_id="stella",
            universe_id=universe_id,
            canonical_name="Stella Ling",
            family_id="ling",
            default_surname="Ling",
            species_baseline="alien_fox_siren",
            home_location="Ling House",
            inheritance_model={"can_self_morph": True, "can_target_morph": False, "no_father": True},
            baseline_notes="Origami-paper fox siren daughter of Francine and Rainee.",
        ),
        CharacterMind(
            character_id="haley",
            universe_id=universe_id,
            canonical_name="Haley Ling",
            family_id="ling",
            default_surname="Ling",
            species_baseline="human_dormant_fox",
            home_location="Ling House",
            inheritance_model={
                "no_father": True,
                "maternal_genetic_mirror": "strong",
                "awakening_destiny": True,
            },
            baseline_notes="Born mostly human with dormant fox genetics destined to awaken; awakened attraction strongly mirrors her mothers.",
        ),
        CharacterMind(
            character_id="noir",
            universe_id=universe_id,
            canonical_name="Noir Ling",
            family_id="ling",
            default_surname="Ling",
            species_baseline="alien_fox_siren",
            home_location="Ling House",
            baseline_notes="Fox woman who once dated a man alongside having wives and girlfriends.",
        ),
        CharacterMind(
            character_id="jeff",
            universe_id=universe_id,
            canonical_name="Jeff Fischer",
            family_id=None,
            default_surname="Fischer",
            species_baseline="human_standard",
            aliases=("Jess",),
            inheritance_model={"linked_alter_ids": ["jess"]},
            baseline_notes="Haley's boyfriend in Spring Break-Up; married husband by Hot Scoomp; gains Jess transformation device in Tapped Out.",
        ),
        CharacterMind(
            character_id="jess",
            universe_id=universe_id,
            canonical_name="Jess",
            family_id=None,
            default_surname="Fischer",
            species_baseline="human_transformed_form",
            baseline_notes="Female transformed form assumed by Jeff via transformation device in Tapped Out.",
        ),
        CharacterMind(
            character_id="holly_graham",
            universe_id=universe_id,
            canonical_name="Holly Graham",
            family_id=None,
            default_surname="Graham",
            species_baseline="human_standard",
            aliases=("HG", "Holly"),
            baseline_notes="Gym / Booty Cult leader with whom awakened Haley has an affair during Hot Scoomp.",
        ),
    )
    for mind in minds:
        upsert_character_mind(conn, mind)

    traits = (
        CharacterTrait(
            trait_id="noir_orientation_exception",
            universe_id=universe_id,
            owner_id="noir",
            trait_kind="orientation_exception",
            predicate="attraction",
            value=["women", "rare_man"],
            grants_law_exception_id="fox_sapphic_tendency",
            evidence_summary="Noir dated a guy once in addition to having wives and girlfriends.",
        ),
        CharacterTrait(
            trait_id="haley_strong_maternal_mirror",
            universe_id=universe_id,
            owner_id="haley",
            trait_kind="genetic_disposition",
            predicate="post_awakening_attraction",
            value={"mirrors_mothers": "strong", "repulsed_by_male_spouse": True},
            evidence_summary="Upon awakening, Haley's genetics mirror her mothers strongly, making her physically repulsed by Jeff.",
            active_from_pos=20.0,
            active_from_beat=2,
        ),
    )
    for trait in traits:
        grant_trait(conn, trait)


def _seed_memories(conn: sqlite3.Connection, universe_id: str) -> None:
    memories = (
        CharacterMemory(
            memory_id="mem_francine_ling_identity",
            universe_id=universe_id,
            owner_scope="personal",
            owner_id="francine",
            subject_id="francine",
            predicate="surname_and_stan",
            object_value="Francine Ling never married Stan Smith",
            truth_status="established_fact",
            episode_pos=0.0,
            beat=0,
        ),
        CharacterMemory(
            memory_id="mem_ling_house_shared",
            universe_id=universe_id,
            owner_scope="family",
            owner_id="ling",
            subject_id="ling_house",
            predicate="household_name",
            object_value="Ling House",
            truth_status="established_fact",
            episode_pos=0.0,
            beat=0,
        ),
    )
    for mem in memories:
        record_memory(conn, mem)


def _seed_timeline_deltas(conn: sqlite3.Connection, universe_id: str) -> None:
    deltas = (
        StateDelta(
            delta_id="d_00_francine_rainee_married",
            universe_id=universe_id,
            branch="main",
            episode_id="origin",
            episode_pos=0.0,
            beat=0,
            seq=1,
            op="SET_RELATIONSHIP",
            subject_id="francine",
            target_id="rainee",
            payload={"status": "married_lesbian_couple", "allowed_terms": ["wife", "wives", "married", "spouse"]},
        ),
        StateDelta(
            delta_id="d_00_haley_dormant_origin",
            universe_id=universe_id,
            branch="main",
            episode_id="origin",
            episode_pos=0.0,
            beat=0,
            seq=2,
            op="SET_BIOLOGY_STAGE",
            subject_id="haley",
            payload={"stage": "dormant_hybrid", "can_self_morph": False, "can_target_morph": False, "traits_manifested": []},
        ),
        StateDelta(
            delta_id="d_00_haley_baseline_attraction",
            universe_id=universe_id,
            branch="main",
            episode_id="origin",
            episode_pos=0.0,
            beat=0,
            seq=3,
            op="SET_ATTRACTION_PROFILE",
            subject_id="haley",
            payload={"attracted_to": ["men"], "repulsed_by": []},
        ),
        StateDelta(
            delta_id="d_10_spring_break_boyfriend",
            universe_id=universe_id,
            branch="main",
            episode_id="spring-break",
            episode_pos=10.0,
            beat=0,
            seq=1,
            op="SET_RELATIONSHIP",
            subject_id="haley",
            target_id="jeff",
            payload={
                "status": "dating",
                "allowed_terms": ["boyfriend", "dating"],
                "anachronistic_terms": ["husband", "married", "wife"],
            },
        ),
        StateDelta(
            delta_id="d_15_show_marriage_inherited",
            universe_id=universe_id,
            branch="main",
            episode_id="post-spring-marriage",
            episode_pos=15.0,
            beat=0,
            seq=1,
            op="SET_RELATIONSHIP",
            subject_id="haley",
            target_id="jeff",
            payload={
                "status": "married",
                "allowed_terms": ["husband", "married", "wife"],
                "anachronistic_terms": [],
            },
            authority="show_progression_import",
        ),
        StateDelta(
            delta_id="d_20_hot_scoomp_awakening",
            universe_id=universe_id,
            branch="main",
            episode_id="hot-scoomp",
            episode_pos=20.0,
            beat=2,
            seq=1,
            op="SET_BIOLOGY_STAGE",
            subject_id="haley",
            payload={
                "stage": "awakened_fox",
                "can_self_morph": True,
                "can_target_morph": True,
                "traits_manifested": ["fox_ears", "fox_tail", "siren_pheromone", "avatars"],
                "trigger": "hot_scoomp_awakening",
            },
        ),
        StateDelta(
            delta_id="d_20_hot_scoomp_repulsion",
            universe_id=universe_id,
            branch="main",
            episode_id="hot-scoomp",
            episode_pos=20.0,
            beat=2,
            seq=2,
            op="SET_ATTRACTION_PROFILE",
            subject_id="haley",
            payload={
                "attracted_to": ["women", "holly_graham", "jess"],
                "repulsed_by": ["jeff"],
                "reason": "mirrors_mothers_genetics_strongly",
            },
        ),
        StateDelta(
            delta_id="d_20_hot_scoomp_holly_affair",
            universe_id=universe_id,
            branch="main",
            episode_id="hot-scoomp",
            episode_pos=20.0,
            beat=2,
            seq=3,
            op="SET_RELATIONSHIP",
            subject_id="haley",
            target_id="holly_graham",
            payload={"status": "affair_cheating", "concurrent_with_marriage": True},
        ),
        StateDelta(
            delta_id="d_30_tapped_out_jess_device",
            universe_id=universe_id,
            branch="main",
            episode_id="tapped-out",
            episode_pos=30.0,
            beat=0,
            seq=1,
            op="GRANT_DEVICE",
            subject_id="jeff",
            payload={
                "device_id": "jess_intimacy_device",
                "transforms_to": "jess",
                "context": "intimacy_and_marriage_salvage",
            },
        ),
        StateDelta(
            delta_id="d_30_tapped_out_marriage_salvage",
            universe_id=universe_id,
            branch="main",
            episode_id="tapped-out",
            episode_pos=30.0,
            beat=0,
            seq=2,
            op="SET_RELATIONSHIP_FACET",
            subject_id="haley",
            target_id="jeff",
            payload={
                "status": "married_salvaged_via_jess",
                "partner_form": "jess",
                "salvage_mechanism": "jess_intimacy_device",
            },
        ),
    )
    for delta in deltas:
        append_delta(conn, delta)
