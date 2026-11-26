"""Unit tests for Stage 1 -> Stage 2 Simulate-Then-Render contracts."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

from pydantic import ValidationError

from story_graph.canon_models import StoryCoord
from story_graph.simulation import (
    AgentIntentProposal,
    BeatBlackboard,
    BeatDiscoursePlan,
    CausalTemporalBridge,
    DirectedRelationshipEdge,
    SimulationModelPort,
    TypedMediaPin,
    UpliftSlotPolicy,
)


def _sample_catalyst_pin() -> TypedMediaPin:
    return TypedMediaPin(
        asset_id="pretty_girls_farting.mp4",
        sha256="a94a8fe5ccb19ba61c4c0873d391e987982fbbd3",
        pin_role="catalyst_trigger",
        stage_a_track_ref="lance://media_tracks/pretty_girls_farting_v1",
        bridging_stage_direction=(
            "Perfume-scented extreme blast bloats Rainee into Big Booty Peter Griffin in Branch A "
            "or splits her into three grumpy Mean Girls personas in Branch B."
        ),
    )


def _sample_francine_edges() -> list[DirectedRelationshipEdge]:
    pin = _sample_catalyst_pin()
    base_edge = DirectedRelationshipEdge(
        edge_id="rel_francine_to_rainee_super_butt",
        universe_id="afm",
        source_character_id="francine",
        source_form_id="francine_base",
        target_character_id="rainee",
        target_form_id="rainee_big_butt",
        inherits_from=None,
        scope_branch="main",
        from_episode_pos=0.0,
        directional_stance={
            "trust": 0.90,
            "patience": 0.78,
            "affection": 0.96,
            "comedic_friction": 0.35,
            "subjective_perception": "Devoted glamorous wife who loves Rainee's Super Butt base form.",
        },
        stage_directions=["Keep baseline married chemistry warm, teasing, and conspiratorial."],
        media_pins=[],
        authority="author_override",
    )
    branch_a_edge = DirectedRelationshipEdge(
        edge_id="rel_francine_to_big_booty_peter",
        universe_id="afm",
        source_character_id="francine",
        source_form_id="francine_base",
        target_character_id="rainee",
        target_form_id="rainee_big_booty_peter_griffin",
        inherits_from=base_edge.edge_id,
        scope_branch="branch_a_peter",
        from_episode_pos=10.0,
        directional_stance={
            "trust": 0.80,
            "patience": 0.42,
            "affection": 0.88,
            "comedic_friction": 0.86,
            "subjective_perception": "Shocked yet fiercely protective: My Wife Is a Big Booty Peter Griffin!",
        },
        stage_directions=[
            "React with deadpan disbelief to Peter-Rainee's swagger while still treating her as her spouse."
        ],
        media_pins=[pin],
        authority="author_override",
    )
    branch_b_edge = DirectedRelationshipEdge(
        edge_id="rel_francine_to_three_little_bitches",
        universe_id="afm",
        source_character_id="francine",
        source_form_id="francine_base",
        target_character_id="rainee",
        target_form_id="rainee_three_little_bitches",
        inherits_from=base_edge.edge_id,
        scope_branch="branch_b_3bitches",
        from_episode_pos=10.0,
        directional_stance={
            "trust": 0.72,
            "patience": 0.25,
            "affection": 0.84,
            "comedic_friction": 0.94,
            "subjective_perception": "Exhausted trying to wrangle three perfume-fume-irritated Mean Girls wives.",
        },
        stage_directions=[
            "Answer Clarie/Becky/Sade snark with exasperated spousal authority, never like strangers."
        ],
        media_pins=[pin],
        authority="author_override",
    )
    reverse_b_edge = DirectedRelationshipEdge(
        edge_id="rel_three_little_bitches_to_francine",
        universe_id="afm",
        source_character_id="rainee",
        source_form_id="rainee_three_little_bitches",
        target_character_id="francine",
        target_form_id="francine_base",
        inherits_from=None,
        scope_branch="branch_b_3bitches",
        from_episode_pos=10.0,
        directional_stance={
            "trust": 0.65,
            "patience": 0.18,
            "affection": 0.70,
            "comedic_friction": 0.95,
            "subjective_perception": "Irritable from the tuberose-perfume blast; deflecting blame while still wanting Francine's backup.",
        },
        stage_directions=["Bicker in unison, then immediately gang up if Francine doubts their dramatic exit."],
        media_pins=[pin],
        authority="author_override",
    )
    return [base_edge, branch_a_edge, branch_b_edge, reverse_b_edge]


class TestSimulationContracts(unittest.TestCase):
    def test_rainee_francine_variant_relationships_round_trip(self):
        edges = _sample_francine_edges()
        self.assertEqual(len(edges), 4)
        for edge in edges:
            raw = edge.model_dump_json()
            rebuilt = DirectedRelationshipEdge.model_validate_json(raw)
            self.assertEqual(rebuilt, edge)

        f_to_trio = edges[2]
        trio_to_f = edges[3]
        self.assertNotEqual(
            f_to_trio.directional_stance["subjective_perception"],
            trio_to_f.directional_stance["subjective_perception"],
        )
        self.assertEqual(f_to_trio.media_pins[0].asset_id, "pretty_girls_farting.mp4")
        self.assertEqual(f_to_trio.media_pins[0].pin_role, "catalyst_trigger")

    def test_blackboard_and_discourse_plan_round_trip(self):
        edges = _sample_francine_edges()
        coord = StoryCoord(
            universe_id="afm",
            branch="branch_b_3bitches",
            episode_id="spring-break",
            episode_position=10.0,
            beat=4,
        )
        proposals = [
            AgentIntentProposal(
                agent_id="agent_francine",
                character_id="francine",
                form_id="francine_base",
                epistemic_snapshot_digest="ep_f_001",
                goal="Restore order in the kitchen before the road trip derails.",
                speech_act="spousal_command",
                target_id="rainee_three_little_bitches",
                proposed_action="Block the red sedan keys until all three stop blaming Haley.",
                intensity=0.82,
            ),
            AgentIntentProposal(
                agent_id="agent_3bitches",
                character_id="rainee",
                form_id="rainee_three_little_bitches",
                epistemic_snapshot_digest="ep_r_004",
                goal="Escape the perfume-fume embarrassment by seizing the high ground.",
                speech_act="mean_girls_deflection",
                target_id="francine_base",
                proposed_action="Clarie cites protocol while Sade grabs the overnight bag.",
                intensity=0.91,
            ),
        ]
        blackboard = BeatBlackboard(
            coord=coord,
            world_state_digest="wt_sb_b04_v1",
            active_forms={"francine": "francine_base", "rainee": "rainee_three_little_bitches"},
            active_relationships=[edges[2], edges[3]],
            stage_b_practices=[{"practice": "perfume_fume_irritability_split", "source": "pretty_girls_farting.mp4"}],
            proposals=proposals,
            arbitration_decisions=[{"winner": "collision_compromise", "outcome": "Francine confiscates keys while trio roasts in unison."}],
            blocked_law_violations=[],
        )
        bb_rebuilt = BeatBlackboard.model_validate_json(blackboard.model_dump_json())
        self.assertEqual(bb_rebuilt, blackboard)

        plan = BeatDiscoursePlan(
            beat_id="B04",
            pdg_input_hash="sha256:9f86d081884c7d659a2feaa0c55ad015",
            cache_status="RECOMPUTED",
            locked_anchors=[{"span_id": "lock_1", "start": 48, "end": 102, "text": '"You are NOT taking the red sedan like this!"'}],
            slot_policies=[
                UpliftSlotPolicy.for_tier("slot_intro", 0, 48, 50),
                UpliftSlotPolicy.for_tier("slot_lock_1", 48, 102, 0),
                UpliftSlotPolicy.for_tier("slot_reaction", 102, 220, 75),
            ],
            emergent_beats=[{"beat": "Francine dangles the sedan keys over the granite island."}],
            delta_receipts=[{"op": "SET_RELATIONSHIP_FACET", "target": "rel_francine_to_three_little_bitches", "patience_delta": -0.1}],
            collision_trace=[{"pair": "francine<->rainee_three_little_bitches", "friction": 0.94}],
        )
        plan_rebuilt = BeatDiscoursePlan.model_validate_json(plan.model_dump_json())
        self.assertEqual(plan_rebuilt, plan)
        self.assertEqual(plan_rebuilt.slot_policies[1].max_token_divergence, 0.0)

    def test_hard_lock_zero_uplift_validation(self):
        valid_lock = UpliftSlotPolicy.for_tier("locked_quote", 10, 42, 0)
        self.assertEqual(valid_lock.max_token_divergence, 0.0)
        self.assertEqual(valid_lock.temperature, 0.0)

        with self.assertRaises(ValidationError):
            UpliftSlotPolicy(
                slot_id="bad_lock_div",
                start=10,
                end=42,
                uplift_pct=0,
                max_token_divergence=0.15,
                min_token_divergence=0.0,
                style_ref_count=0,
                temperature=0.0,
            )

        with self.assertRaises(ValidationError):
            UpliftSlotPolicy(
                slot_id="bad_lock_temp",
                start=10,
                end=42,
                uplift_pct=0,
                max_token_divergence=0.0,
                min_token_divergence=0.0,
                style_ref_count=0,
                temperature=0.4,
            )

    def test_temporal_bridge_requires_carrier_character(self):
        bridge = CausalTemporalBridge(
            bridge_id="tt_ep6_to_ep2",
            origin_branch="main",
            origin_pos=60.0,
            origin_beat=9,
            target_branch="tt_branch_1",
            target_pos=20.0,
            target_beat=2,
            carrier_character_id="rainee",
            carried_memory_ids=["mem_future_sedan_crash", "mem_peter_trigger"],
        )
        rebuilt = CausalTemporalBridge.model_validate_json(bridge.model_dump_json())
        self.assertEqual(rebuilt, bridge)

        with self.assertRaises(ValidationError):
            CausalTemporalBridge(
                bridge_id="tt_invalid",
                origin_branch="main",
                origin_pos=60.0,
                origin_beat=9,
                target_branch="tt_branch_1",
                target_pos=20.0,
                target_beat=2,
                carrier_character_id="   ",
                carried_memory_ids=["mem_leak"],
            )

    def test_catalyst_pin_requires_bridging_stage_direction(self):
        with self.assertRaises(ValidationError):
            TypedMediaPin(
                asset_id="pretty_girls_farting.mp4",
                sha256="deadbeef",
                pin_role="catalyst_trigger",
                stage_a_track_ref="lance://media_tracks/test",
                bridging_stage_direction="   ",
            )

    def test_stance_bounds_and_protocol_and_layer_boundary(self):
        with self.assertRaises(ValidationError):
            DirectedRelationshipEdge(
                edge_id="bad_stance",
                universe_id="afm",
                source_character_id="francine",
                source_form_id="francine_base",
                target_character_id="rainee",
                target_form_id="rainee_big_butt",
                directional_stance={
                    "trust": 0.9,
                    "patience": 1.5,
                    "affection": 0.9,
                    "comedic_friction": 0.2,
                    "subjective_perception": "Invalid patience > 1.0",
                },
            )

        class _MockSimAdapter:
            def propose_intent(self, blackboard, character_id, form_id):
                return blackboard.proposals[0]

            def arbitrate_blackboard(self, blackboard):
                return BeatDiscoursePlan(beat_id="B04", pdg_input_hash="h", cache_status="RECOMPUTED")

        self.assertIsInstance(_MockSimAdapter(), SimulationModelPort)

        src = Path("story_graph/simulation/contracts.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("prose_engine", imported)
        self.assertNotIn("tools", imported)


if __name__ == "__main__":
    unittest.main()
