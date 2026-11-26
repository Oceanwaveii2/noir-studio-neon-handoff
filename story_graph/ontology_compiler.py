"""
story_graph/ontology_compiler.py
Compiles active ontological rules and negative constraints from OntologyGraph
into BeatPackets and ProseRewriteRequests.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from .compiler import BeatPacket
from .ontology import OntologyGraph, SpeciesType


class OntologyCompiler:
    """
    Compiles formal ontological invariants from an OntologyGraph into
    actionable positive rules and negative regex patterns for the Prose Engine.
    """

    def __init__(self, ontology: Optional[OntologyGraph] = None):
        self.ontology = ontology or OntologyGraph.create_canonical_foxy_mo2()

    def compile_beat_ontology(
        self,
        characters_present: List[str],
        characters_adjacent: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Compiles the ontological sub-graph relevant to the active scene participants.
        """
        all_chars = set(c.lower() for c in characters_present)
        if characters_adjacent:
            all_chars.update(c.lower() for c in characters_adjacent)

        # Character species & morph capability
        char_data = {}
        for c_id in all_chars:
            species_type = self.ontology.character_species.get(c_id, SpeciesType.HUMAN_STANDARD)
            trait = self.ontology.species_registry.get(species_type)
            can_self = self.ontology.character_morph_capabilities.get(c_id, {}).get(
                "can_self_morph", trait.can_self_morph if trait else False
            )
            can_target = self.ontology.can_character_target_morph(c_id)

            if trait:
                char_data[c_id] = {
                    "species": trait.species_id.value,
                    "is_all_female_species": trait.is_all_female_species,
                    "ageless": trait.has_agelessness,
                    "chronological_age": trait.chronological_age,
                    "visual_age_range": list(trait.visual_age_range),
                    "can_self_morph": can_self,
                    "can_target_morph": can_target,
                    "seat_units_required": trait.default_seat_units_required,
                }
            else:
                char_data[c_id] = {
                    "species": species_type.value,
                    "can_self_morph": can_self,
                    "can_target_morph": can_target,
                    "seat_units_required": 1,
                }

        # Active kinship links between present characters
        kinship = []
        for rel in self.ontology.kinship_relations:
            if rel.subject_id in all_chars or rel.target_id in all_chars:
                kinship.append({
                    "subject": rel.subject_id,
                    "target": rel.target_id,
                    "relation": rel.relation_type.value,
                    "notes": rel.notes,
                    "forbid_terms": rel.forbid_terms,
                })

        # Active auras emitted by present characters
        auras = []
        for aura in self.ontology.active_auras.values():
            if aura.emitter_id in all_chars:
                auras.append({
                    "field_id": aura.field_id,
                    "emitter": aura.emitter_id,
                    "aura_type": aura.aura_type.value,
                    "intensity": aura.intensity,
                    "effect": aura.effect_description,
                    "target_demographic": aura.target_demographic,
                })

        return {
            "characters": char_data,
            "kinship": kinship,
            "auras": auras,
            "positive_invariants": self.ontology.get_summary_invariants(),
            "negative_constraints": self.ontology.hard_negative_rules,
            "canon_divergences": self.ontology.canon_divergences,
        }

    def enrich_beat_packet(self, packet: BeatPacket) -> BeatPacket:
        """Enriches an existing BeatPacket with ontological context and negative constraints."""
        onto_data = self.compile_beat_ontology(
            characters_present=packet.characters_present,
            characters_adjacent=packet.characters_adjacent,
        )
        packet.ontological_context = onto_data
        packet.negative_constraints = self.ontology.hard_negative_rules
        return packet
