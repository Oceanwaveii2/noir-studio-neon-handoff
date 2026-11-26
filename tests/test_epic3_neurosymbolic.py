"""Epic 3 verification: media_analysis/, sensory typed laws, complement epistemic bounds, and MindProjectionResolver."""
from __future__ import annotations

import math
from pathlib import Path
import struct
import tempfile
import unittest
import wave

from prose_engine.invariant_gate import InvariantGate
from prose_engine.media_analysis import Evidence, analyze_clip
from prose_engine.scoped_pipeline import ScopedPacket, validate_output
from story_graph.canon_models import CompiledWorldState, StoryCoord
from story_graph.compiler import BeatPacketCompiler
from story_graph.epistemic import EpistemicLedger, Fact
from story_graph.mind_resolver import InteractionRule, MindProjectionResolver, check_interaction_rules
from story_graph.typed_laws import KINDS, validate_constraint
from story_graph.world_state import CharacterState, Location, StoryWorldState


def _write_test_wav(path: Path) -> None:
    sr = 8000
    samples: list[int] = []
    # 0.5s tone -> 0.8s silence -> 0.5s tone
    for i in range(int(sr * 0.5)):
        samples.append(int(8000 * math.sin(2 * math.pi * 440 * i / sr)))
    samples.extend([0] * int(sr * 0.8))
    for i in range(int(sr * 0.5)):
        samples.append(int(8000 * math.sin(2 * math.pi * 440 * i / sr)))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class TestEpic3Neurosymbolic(unittest.TestCase):
    def test_media_analysis_pause_envelope_and_evidence_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "pause.wav"
            _write_test_wav(wav)
            env = analyze_clip(wav)
            self.assertEqual(env.schema_version, 1)
            self.assertGreaterEqual(len(env.pause_windows), 1)
            guidance = env.to_rhythm_guidance()
            self.assertGreaterEqual(guidance["longest_hold_sec"], 0.7)
            self.assertTrue(guidance["cues"])

            ev_unreviewed = Evidence("audio", "clip-1", "t=0.5-1.3", "rev-1", "raw sound")
            with self.assertRaises(PermissionError):
                ev_unreviewed.context()
            ev_ok = Evidence("audio", "clip-1", "t=0.5-1.3", "rev-1", "raw sound", reviewed="0.8s comedic hold", reviewer="author", permission="permitted")
            self.assertEqual(ev_ok.context()["text"], "0.8s comedic hold")

    def test_sensory_typed_laws_accept_emission_and_propagation(self):
        self.assertIn("physiological_emission", KINDS)
        self.assertIn("sensory_propagation", KINDS)
        validate_constraint({
            "kind": "physiological_emission",
            "subject": "rainee",
            "predicate": "siren_pheromone_target",
            "allowed_values": ["women"],
            "source_id": "afm-biology",
            "authority": "author",
            "branch": "*",
            "valid_from": None,
            "valid_until": None,
            "exceptions": [],
        })

    def test_complement_epistemic_leak_blocks_secret_and_allows_negation(self):
        world = StoryWorldState()
        world.add_location(Location(id="ling_kitchen", name="Ling Kitchen"))
        world.add_character(CharacterState(id="haley", name="Haley Ling", location="ling_kitchen"))
        world.add_character(CharacterState(id="francine", name="Francine Ling", location="ling_kitchen"))

        ledger = EpistemicLedger()
        ledger.register_fact(Fact(id="vault_combo", description="Secret garage pin", keywords=["obsidian passphrase"], is_private=True))
        ledger.register_character("francine", ["vault_combo"])
        ledger.register_character("haley", [])

        pkt = BeatPacketCompiler(world, ledger=ledger).compile({
            "beat_id": "b1",
            "beat_name": "Kitchen",
            "scene_id": "ling_kitchen",
            "primary_character": "haley",
            "tick": 0,
            "description": "Haley grabs coffee.",
            "raw_dialogue": [{"speaker": "haley", "text": "Coffee."}],
        })
        self.assertIn("haley", pkt.epistemic_unknown)
        self.assertEqual([f["id"] for f in pkt.epistemic_unknown["haley"]], ["vault_combo"])

        leaked = InvariantGate.verify_epistemic_bounds(
            "Haley whispered the obsidian passphrase across the counter.",
            pkt.epistemic_context,
            pkt.epistemic_unknown,
        )
        self.assertTrue(leaked)

        negated = InvariantGate.verify_epistemic_bounds(
            "Haley never knew the obsidian passphrase.",
            pkt.epistemic_context,
            pkt.epistemic_unknown,
        )
        self.assertEqual(negated, [])

        # CompiledWorldState hidden_facts also enforced in scoped_pipeline.validate_output
        cstate = CompiledWorldState(
            coord=StoryCoord("afm", "main", "spring-break", 10.0, 0),
            viewpoint="haley",
            hard_invariants=(),
            soft_tendencies=(),
            import_bleed_guards=(),
            characters={},
            relationships={},
            memories=(),
            hidden_facts=({"object_value": "obsidian passphrase", "reason": "withheld"},),
            applied_deltas=(),
            state_digest="abc",
        )
        spkt = ScopedPacket(
            episode="spring-break",
            branch="main",
            beat=0,
            viewpoint="haley",
            revision=0,
            target="Haley picked up her cup.",
            target_sha256="x",
            events=(),
            forms={},
            hidden_phrases=(),
            canon_state=cstate,
        )
        issues = validate_output(spkt, "Haley muttered the obsidian passphrase.")
        self.assertEqual(issues, ["Output contains information unavailable at this beat"])

    def test_mind_projection_resolver_multi_body_and_conditional_rules(self):
        junctions = [{
            "character_id": "rainee",
            "forms": [
                {"id": "rainee_1", "port_id": "p1", "label": "Rainee 1", "status": "active", "link": "mind_1"},
                {"id": "rainee_2", "port_id": "p2", "label": "Rainee 2", "status": "active", "link": "mind_2"},
                {"id": "rainee_3", "port_id": "p3", "label": "Rainee 3", "status": "active", "link": "mind_3"},
                {"id": "rainee_4", "port_id": "p4", "label": "Rainee 4", "status": "active", "link": "mind_4"},
            ],
        }]
        rule = InteractionRule(
            rule_id="r2-back-haley",
            speaker_id="rainee_2",
            when_pressure="quarrel_ended",
            required_acts=("back haley",),
            avoid=("shouted over haley",),
        )
        resolver = MindProjectionResolver()
        bodies = resolver.active_bodies(
            junctions,
            beat_overrides={"p2": {"tactic": "quiet_defector"}},
            interaction_rules=[rule],
            active_pressures=["quarrel_ended"],
        )
        self.assertEqual(len(bodies), 4)
        self.assertIn("beat_override", bodies[1].provenance_layers)
        self.assertEqual(len(bodies[1].active_rules), 1)
        self.assertTrue(check_interaction_rules("Rainee 2 shouted over Haley cleanly.", bodies))
        self.assertEqual(check_interaction_rules("Rainee 2 stepped quietly to back Haley.", bodies), [])

        replay_bodies = resolver.active_bodies(
            junctions,
            replay_frame={"state": {"root": "rainee", "manifestations": [
                {"id": "p1", "location": "kitchen", "mind": "mind_1"},
                {"id": "p4", "location": "yard", "mind": "mind_4"},
            ]}},
            interaction_rules=[rule],
            active_pressures=["quarrel_ended"],
        )
        self.assertEqual([b.form_id for b in replay_bodies], ["rainee_1", "rainee_4"])
