"""
tests/test_ontological_graph.py
Comprehensive Verification Suite for Ontological Story Graph & Real-Time Invariant Guarding.
Milestone O-5: Comprehensive Verification & Test Suite Expansion.

Verifies:
  1. Biological and Species Invariants (100% all-female, agelessness, 3 sisters).
  2. Monosexual Nanomachine Reproduction (NO Stan, NO fathers, NO men).
  3. Natural Biological Siren Pheromones (Yuri Field) - chemical magnetism, zero "mind control" framing.
  4. Dimensional Physical Affordances (Rainee 2-chair seating constraint, double-wide commodes).
  5. Morph Matrix: Rainee (self + others), Stella (self only), Haley (dormant genes, CANNOT shapeshift).
  6. Haley Orientation & Relationship: Heterosexual dating boyfriend Jeff (not a lesbian yet in this episode).
  7. World State Transaction Handlers (_handle_seat_claim, _handle_morph_self, _handle_morph_target).
  8. OntologyCompiler & BeatPacketCompiler Automatic Enrichment.
  9. InvariantGate & GuardrailCoprocessor Real-Time Negative Regex Rejection.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Ensure root directory is on PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from story_graph.models import CharacterState, Location, Posture, Transaction
from story_graph.world_state import StoryWorldState
from story_graph.ontology import (
    AuraType,
    MorphPermission,
    OntologyGraph,
    RelationshipType,
    ReproductionMode,
    SpeciesType,
)
from story_graph.ontology_compiler import OntologyCompiler
from story_graph.compiler import BeatPacket, BeatPacketCompiler
from prose_engine.models import ProseRewriteRequest, ProseDiagnosticReport, SpanCategory
from prose_engine.prompt_assembler import PromptAssembler
from prose_engine.style_engine import StyleProfile
from prose_engine.invariant_gate import InvariantGate
from prose_engine.coprocessor.guardrail import GuardrailCoprocessor


class TestOntologicalStoryGraph(unittest.TestCase):

    def setUp(self):
        self.onto = OntologyGraph.create_canonical_foxy_mo2()
        self.compiler = OntologyCompiler(self.onto)

    # -------------------------------------------------------------------------
    # 1. Biological & Kinship Invariants
    # -------------------------------------------------------------------------

    def test_canonical_species_invariants(self):
        siren_trait = self.onto.species_registry[SpeciesType.ALIEN_FOX_SIREN]
        self.assertTrue(siren_trait.is_all_female_species)
        self.assertFalse(siren_trait.has_patriarchal_lineage)
        self.assertTrue(siren_trait.has_agelessness)
        self.assertEqual(siren_trait.chronological_age, 50)
        self.assertEqual(siren_trait.visual_age_range, (20, 24))
        self.assertEqual(siren_trait.reproduction_mode, ReproductionMode.NANOMACHINE_MONOSEXUAL)
        self.assertEqual(siren_trait.default_seat_units_required, 2)
        self.assertEqual(siren_trait.butt_span_chairs, 2.0)

    def test_haley_dormant_genes_and_heterosexual_dating_status(self):
        """Haley is dormant-fox mostly human and dating boyfriend Jeff in Spring Break-Up."""
        haley_trait = self.onto.species_registry[SpeciesType.HUMAN_DORMANT_FOX]
        self.assertFalse(haley_trait.can_self_morph)
        self.assertFalse(haley_trait.can_target_morph)

        # Check kinship with boyfriend Jeff in Spring Break-Up epoch
        jeff_rel = next((k for k in self.onto.kinship_relations if k.subject_id == "haley" and k.target_id == "jeff"), None)
        self.assertIsNotNone(jeff_rel)
        self.assertEqual(jeff_rel.relation_type, RelationshipType.BOYFRIEND_GIRLFRIEND)
        self.assertIn("not husband yet", jeff_rel.notes.lower())
        self.assertIn("dormant fox genetics", jeff_rel.notes.lower())
        self.assertIn("husband Jeff", jeff_rel.forbid_terms)

    def test_married_lesbian_couple_no_father_or_stan(self):
        """Francine and Rainee are a married lesbian couple with children; no father or Stan."""
        fr_rel = next((k for k in self.onto.kinship_relations if k.subject_id == "francine" and k.target_id == "rainee"), None)
        self.assertIsNotNone(fr_rel)
        self.assertEqual(fr_rel.relation_type, RelationshipType.MARRIED_LESBIAN_COUPLE)
        self.assertIn("father", fr_rel.forbid_terms)
        self.assertIn("husband", fr_rel.forbid_terms)

    # -------------------------------------------------------------------------
    # 2. Siren Pheromones (Yuri Field) - Zero Mind Control Framing
    # -------------------------------------------------------------------------

    def test_siren_pheromones_natural_chemical_magnetism(self):
        aura = self.onto.active_auras["rainee_yuri_field"]
        self.assertEqual(aura.aura_type, AuraType.YURI_FIELD_SIREN_PHEROMONE)
        self.assertEqual(aura.emitter_id, "rainee")
        self.assertEqual(aura.target_demographic, "straight_human_female")
        # Ensure effect description uses natural magnetism and DOES NOT mention mind control
        self.assertIn("chemical magnetism", aura.effect_description.lower())
        self.assertIn("without forcing any decisions", aura.effect_description.lower())
        self.assertNotIn("mind control", aura.effect_description.lower())
        self.assertNotIn("mind_control", aura.effect_description.lower())

    # -------------------------------------------------------------------------
    # 3. Morph Matrix & Character Permissions
    # -------------------------------------------------------------------------

    def test_morph_permissions_matrix(self):
        perms = self.onto.get_character_morph_permissions()
        self.assertTrue(perms["rainee"])
        self.assertTrue(perms["stella"])
        self.assertFalse(perms["haley"])      # Haley CANNOT shapeshift
        self.assertFalse(perms["francine"])   # Francine cannot shapeshift

        # Target morphing (transforming others)
        self.assertTrue(self.onto.can_character_target_morph("rainee"))
        self.assertFalse(self.onto.can_character_target_morph("stella"))  # Stella is self only
        self.assertFalse(self.onto.can_character_target_morph("haley"))
        self.assertFalse(self.onto.can_character_target_morph("francine"))

    # -------------------------------------------------------------------------
    # 4. World State Transactions: Seating & Morph Enforcement
    # -------------------------------------------------------------------------

    def test_world_state_seat_claim_affordance_rainee(self):
        world = StoryWorldState("AffordanceWorld")
        world.add_location(Location(id="living_room", name="Living Room"))
        rainee = CharacterState(id="rainee", name="Rainee", location="living_room", physique={"seat_units_required": 2})
        haley = CharacterState(id="haley", name="Haley", location="living_room", physique={"seat_units_required": 1})
        world.add_character(rainee)
        world.add_character(haley)

        # 1. Rainee attempts to claim a single chair -> FAILS
        res_fail = world.execute(Transaction(action="seat_claim", actor="rainee", target="armchair", params={"chairs_claimed": 1}))
        self.assertFalse(res_fail.success)
        self.assertIn("Affordance Violation", res_fail.reason)

        # 2. Rainee claims 2 chairs -> SUCCEEDS
        res_ok_chairs = world.execute(Transaction(action="seat_claim", actor="rainee", target="loveseat", params={"chairs_claimed": 2}))
        self.assertTrue(res_ok_chairs.success)
        self.assertEqual(rainee.posture, Posture.SEATED)

        # 3. Rainee sits on a custom enlarged commode -> SUCCEEDS
        res_ok_custom = world.execute(Transaction(action="seat_claim", actor="rainee", target="black_lacquer_throne", params={"is_custom_enlarged": True}))
        self.assertTrue(res_ok_custom.success)

        # 4. Haley claims a single standard chair -> SUCCEEDS
        res_haley = world.execute(Transaction(action="seat_claim", actor="haley", target="dining_chair", params={"chairs_claimed": 1}))
        self.assertTrue(res_haley.success)

    def test_world_state_morph_permissions_enforcement(self):
        world = StoryWorldState("MorphWorld")
        world.add_location(Location(id="living_room", name="Living Room"))
        rainee = CharacterState(id="rainee", name="Rainee", location="living_room", physique={"can_self_morph": True, "can_target_morph": True})
        stella = CharacterState(id="stella", name="Stella", location="living_room", physique={"can_self_morph": True, "can_target_morph": False})
        haley = CharacterState(id="haley", name="Haley", location="living_room", physique={"can_self_morph": False, "can_target_morph": False})
        francine = CharacterState(id="francine", name="Francine", location="living_room", physique={"can_self_morph": False, "can_target_morph": False})
        world.add_character(rainee)
        world.add_character(stella)
        world.add_character(haley)
        world.add_character(francine)

        # 1. Haley attempts self-morph -> FAILS
        res_haley = world.execute(Transaction(action="morph_self", actor="haley", target="haley", params={"avatar_id": "fox_form"}))
        self.assertFalse(res_haley.success)
        self.assertIn("Morph Permission Violation", res_haley.reason)

        # 2. Rainee self-morph into Peter Griffin -> SUCCEEDS
        res_rainee_peter = world.execute(Transaction(action="morph_self", actor="rainee", target="rainee", params={"avatar_id": "avatar_peter_griffin"}))
        self.assertTrue(res_rainee_peter.success)
        self.assertEqual(rainee.physique["active_avatar"], "avatar_peter_griffin")

        # 3. Stella attempts target-morph on Francine -> FAILS (Stella is self-morph only)
        res_stella_target = world.execute(Transaction(action="morph_target", actor="stella", target="francine", params={"avatar_id": "glamour_vixen"}))
        self.assertFalse(res_stella_target.success)
        self.assertIn("cannot transform other characters", res_stella_target.reason)

        # 4. Rainee target-morphs Francine into Pamela Anderson -> SUCCEEDS
        res_rainee_target = world.execute(Transaction(action="morph_target", actor="rainee", target="francine", params={"avatar_id": "nurse_pamela_anderson", "clothing": "latex_scrubs"}))
        self.assertTrue(res_rainee_target.success)
        self.assertEqual(francine.physique["active_avatar"], "nurse_pamela_anderson")
        self.assertEqual(francine.clothing, "latex_scrubs")

    # -------------------------------------------------------------------------
    # 5. Compiler Automatic Ontological Enrichment
    # -------------------------------------------------------------------------

    def test_compiler_automatic_enrichment(self):
        world = StoryWorldState("CompilerWorld")
        world.add_location(Location(id="living_room", name="Living Room"))
        world.add_character(CharacterState(id="rainee", name="Rainee", location="living_room"))
        world.add_character(CharacterState(id="haley", name="Haley", location="living_room"))

        # Compiler with ontology_compiler attached
        bp_compiler = BeatPacketCompiler(world=world, ledger=None, ontology_compiler=self.compiler)
        rec = {
            "beat_id": "beat_11_test",
            "scene_id": "living_room",
            "primary_character": "rainee",
            "raw_dialogue": [{"speaker": "RAINEE", "text": "Boyfriend Jeff's tragic lack of rear carriage..."}],
            "transaction_results": []
        }
        packet = bp_compiler.compile(rec)

        # Verify automatic enrichment
        self.assertIsNotNone(packet.ontological_context)
        self.assertIsNotNone(packet.negative_constraints)
        self.assertGreaterEqual(len(packet.negative_constraints), 5)
        self.assertIn("characters", packet.ontological_context)
        self.assertIn("rainee", packet.ontological_context["characters"])
        self.assertIn("haley", packet.ontological_context["characters"])

    # -------------------------------------------------------------------------
    # 6. Real-Time InvariantGate Rejection of Forbidden Hallucinations
    # -------------------------------------------------------------------------

    def test_invariant_gate_negative_constraint_rejections(self):
        request = ProseRewriteRequest(
            request_id="req_001",
            project_id="noir_foxy",
            document_id="doc_mo2",
            base_revision=1,
            target_span_id="span_001",
            original_text="Rainee descended the staircase.",
            ontological_invariants=self.onto.get_summary_invariants(),
            negative_constraints=self.onto.hard_negative_rules,
            character_morph_permissions=self.onto.get_character_morph_permissions(),
        )

        # 1. Hallucinating a father -> REJECTED
        bad_text_1 = "Rainee glared at her daughter. 'Haley, you inherited your father's lack of rear end.'"
        is_valid, violations, _ = InvariantGate.audit_rewrite(bad_text_1, request)
        self.assertFalse(is_valid)
        self.assertTrue(any("father" in v.lower() for v in violations))

        # 2. Hallucinating Stan or Smith surname -> REJECTED
        bad_text_2 = "Stan Smith walked in from the garage and kissed Francine."
        is_valid, violations, _ = InvariantGate.audit_rewrite(bad_text_2, request)
        self.assertFalse(is_valid)
        self.assertTrue(any("stan" in v.lower() or "smith" in v.lower() for v in violations))

        bad_text_smith_ling = "Haley Smith-Ling looked up from her smartphone with a sigh."
        is_valid_sl, violations_sl, _ = InvariantGate.audit_rewrite(bad_text_smith_ling, request)
        self.assertFalse(is_valid_sl)
        self.assertTrue(any("smith" in v.lower() for v in violations_sl))

        # 3. Hallucinating husband Jeff -> REJECTED
        bad_text_3 = "Haley adjusted her headband while thinking about her husband Jeff."
        is_valid, violations, _ = InvariantGate.audit_rewrite(bad_text_3, request)
        self.assertFalse(is_valid)
        self.assertTrue(any("husband jeff" in v.lower() for v in violations))

        # 4. Hallucinating Haley shapeshifting -> REJECTED
        bad_text_4 = "Haley gasped as she transformed into a fox and flicked her pointed ears."
        is_valid, violations, _ = InvariantGate.audit_rewrite(bad_text_4, request)
        self.assertFalse(is_valid)
        self.assertTrue(any("haley" in v.lower() and ("shapeshift" in v.lower() or "morph" in v.lower()) for v in violations))

        # 5. Hallucinating Haley as a lesbian or siren in this episode -> REJECTED
        bad_text_5 = "Haley felt her inner lesbian siren aura awaken as she gazed at the women."
        is_valid, violations, _ = InvariantGate.audit_rewrite(bad_text_5, request)
        self.assertFalse(is_valid)
        self.assertTrue(any("haley" in v.lower() for v in violations))

        # 6. Valid Canonical Prose (with Baba Ling allowed) -> ACCEPTED
        good_text = (
            "Rainee descended the polished steps, emerald satin gripping her voluminous two-chair hips. "
            "She looked at Haley with an amused smirk. 'Haley, sweetie, just because you inherited your "
            "boyfriend Jeff's tragic flat-white-boy rear is no excuse to be catty.' "
            "Haley blinked twice, taking three full seconds to process the biological absurdity."
        )
        is_valid, violations, _ = InvariantGate.audit_rewrite(good_text, request)
        self.assertTrue(is_valid, f"Violations unexpectedly flagged: {violations}")

        # Francine's adoptive father Baba Ling is permitted
        good_text_baba = (
            "Francine explained that she had to visit Baba Ling in the hospital all week while he recovered "
            "from his inguinal hernia surgery, manually pressing his abdomen to fart him."
        )
        is_valid_baba, violations_baba, _ = InvariantGate.audit_rewrite(good_text_baba, request)
        self.assertTrue(is_valid_baba, f"Baba Ling unexpectedly flagged: {violations_baba}")

    # -------------------------------------------------------------------------
    # 7. Real-Time Guardrail Coprocessor Screening
    # -------------------------------------------------------------------------

    def test_guardrail_coprocessor_ontological_screening(self):
        guardrail = GuardrailCoprocessor()

        # Text with patriarchal breach
        bad_text = "Haley looked at her father's portrait on the mantle."
        report = guardrail.audit_text(
            bad_text,
            ontology_negative_rules=self.onto.hard_negative_rules,
            character_morph_permissions=self.onto.get_character_morph_permissions(),
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("ONTOLOGY_BREACH" in v for v in report.ai_tell_violations))

        # Text with Haley unauthorized morph
        morph_breach_text = "Haley concentrated deeply and her body morphed into a silver kitsune."
        report_morph = guardrail.audit_text(
            morph_breach_text,
            ontology_negative_rules=self.onto.hard_negative_rules,
            character_morph_permissions=self.onto.get_character_morph_permissions(),
        )
        self.assertFalse(report_morph.passed)
        self.assertFalse(report_morph.is_clean_of_ontological_breaches)
        self.assertTrue(any("MORPH_BREACH" in v for v in report_morph.ontological_violations))

    # -------------------------------------------------------------------------
    # 8. Milestone O-3: PromptAssembler Closed-Loop Assembly & Packet Conversion
    # -------------------------------------------------------------------------

    def test_from_beat_packet_and_prompt_assembler_wiring(self):
        """Milestone O-3: Constructs ProseRewriteRequest from BeatPacket and verifies prompt assembly."""
        world = StoryWorldState("PromptWorld")
        world.add_location(Location(id="living_room", name="Living Room"))
        world.add_character(CharacterState(id="rainee", name="Rainee", location="living_room"))
        world.add_character(CharacterState(id="haley", name="Haley", location="living_room"))

        bp_compiler = BeatPacketCompiler(world=world, ledger=None, ontology_compiler=self.compiler)
        rec = {
            "beat_id": "beat_11_staircase_descent_jeff_ass_quip",
            "scene_id": "living_room",
            "primary_character": "rainee",
            "description": "Rainee steps into the living room, confronting Haley.",
            "raw_dialogue": [
                {
                    "speaker": "RAINEE",
                    "parenthetical": "voice strained",
                    "text": "Haley... sweetie... just because you inherited your boyfriend Jeff's tragic flat-white-boy rear carriage is no excuse to be catty... Hhhk!",
                    "frozen": True,
                }
            ],
            "transaction_results": []
        }
        packet = bp_compiler.compile(rec)

        # 1. Convert BeatPacket to ProseRewriteRequest
        request = ProseRewriteRequest.from_beat_packet(packet)
        self.assertEqual(request.request_id, "req_beat_11_staircase_descent_jeff_ass_quip")
        self.assertGreaterEqual(len(request.ontological_invariants), 5)
        self.assertGreaterEqual(len(request.negative_constraints), 5)
        self.assertFalse(request.character_morph_permissions["haley"])
        self.assertTrue(request.character_morph_permissions["rainee"])
        self.assertEqual(len(request.protected_spans), 1)
        self.assertIn("boyfriend Jeff's", request.protected_spans[0].text)

        # 2. Assemble Prompt via PromptAssembler
        diagnostics = ProseDiagnosticReport(span_id="span-0")
        style_profile = StyleProfile(
            profile_id="foxy_scoomp",
            name="American Foxy Hot Scoomp",
            description="High-energy animated sitcom prose with sharp comedic dialogue.",
            target_cadence_burstiness=5.5,
            voice_principles=["Deadpan farce", "High-velocity slapstick"],
        )
        prompt = PromptAssembler.assemble(
            request=request,
            diagnostics=diagnostics,
            style_profile=style_profile,
            approved_edits=[],
            reference_passages=[],
        )

        # 3. Assert All Ontological Prompt Sections Are Present
        self.assertIn("=== INVIOLABLE ONTOLOGICAL & BIOLOGICAL INVARIANTS ===", prompt)
        self.assertIn("=== CHARACTER SHAPESHIFTING PERMISSIONS ===", prompt)
        self.assertIn("=== NEGATIVE CONSTRAINTS (FORBIDDEN HALLUCINATIONS) ===", prompt)
        self.assertIn("HALEY: STRICTLY FORBIDDEN from shapeshifting / morphing", prompt)
        self.assertIn("RAINEE: PERMITTED to shapeshift / morph", prompt)
        self.assertIn("FORBIDDEN:", prompt)
        self.assertIn("boyfriend Jeff's tragic flat-white-boy rear carriage", prompt)

        # 4. Strict Zero "Mind Control" framing invariant across entire assembled prompt
        self.assertNotIn("mind control", prompt.lower())
        self.assertNotIn("mind_control", prompt.lower())

    # -------------------------------------------------------------------------
    # 9. Milestone O-5: Comprehensive System-Wide Invariant & Codebase Audit
    # -------------------------------------------------------------------------

    def test_codebase_zero_mind_control_audit(self):
        """Milestone O-5: Programmatically verifies zero occurrences of mind control in story_graph and prose_engine."""
        import re
        banned_pattern = re.compile(r"mind[_ ]control", re.IGNORECASE)
        for base_dir in ["story_graph", "prose_engine"]:
            target_path = ROOT / base_dir
            for py_file in target_path.rglob("*.py"):
                content = py_file.read_text(encoding="utf-8")
                matches = banned_pattern.findall(content)
                self.assertEqual(
                    len(matches),
                    0,
                    f"Forbidden 'mind control' framing detected in {py_file}: {matches}"
                )


if __name__ == "__main__":
    unittest.main()
