"""
Unit tests for Milestone M-SG4: Beat Packet Compiler.
Verifies compilation of execution logs into structured BeatPackets,
JSON manifest serialization, and Screenplay Markdown generation.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure root directory is on PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from story_graph import (
    BeatPacket,
    BeatPacketCompiler,
    BeatSequencer,
)
from story_graph.scenarios.spring_breakup import build_spring_breakup_world
from story_graph.scenarios.spring_breakup_dag import build_spring_breakup_dag
from story_graph.scenarios.spring_breakup_epistemic import build_spring_breakup_epistemic_ledger


class TestStoryGraphCompiler(unittest.TestCase):

    def setUp(self):
        self.world = build_spring_breakup_world()
        self.dag = build_spring_breakup_dag()
        self.ledger = build_spring_breakup_epistemic_ledger()
        self.sequencer = BeatSequencer(self.dag, self.world)
        self.compiler = BeatPacketCompiler(self.world, self.ledger)

    def test_compile_single_beat_packet(self):
        rec = self.sequencer.execute_beat("beat_01_francine_kitchen_briefing")
        packet = self.compiler.compile(rec)

        self.assertEqual(packet.beat_id, "beat_01_francine_kitchen_briefing")
        self.assertEqual(packet.scene_id, "scene_01_kitchen_living")
        self.assertIn("KITCHEN", packet.slugline)
        self.assertIn("francine", packet.characters_present)
        self.assertIn("haley", packet.characters_adjacent)
        self.assertEqual(len(packet.raw_dialogue), 3)
        self.assertIn("suburban_authority", packet.aesthetic_tags)

    def test_rewrite_prompt_keeps_inventory_private_knowledge_and_reveals_separate(self):
        from prose_engine.models import ProseDiagnosticReport, ProseRewriteRequest
        from prose_engine.prompt_assembler import PromptAssembler
        from prose_engine.style_engine import STANDARD_DRAMATIC
        from story_graph.epistemic import EpistemicLedger, Fact
        from story_graph.models import CharacterState, Location, PropState
        from story_graph.world_state import StoryWorldState

        world = StoryWorldState()
        world.add_location(Location('hall', 'Hall'))
        world.add_character(CharacterState('ana', 'Ana', 'hall', inventory=['blue_key']))
        world.add_character(CharacterState('bea', 'Bea', 'hall', inventory=['red_key']))
        world.add_prop(PropState('blue_key', 'Blue key', 'held:ana'))
        world.add_prop(PropState('red_key', 'Red key', 'held:bea', {'state': 'broken'}))
        ledger = EpistemicLedger()
        ledger.register_fact(Fact('blue_hidden', 'Only Ana knows its origin'))
        ledger.register_fact(Fact('red_hidden', 'Only Bea knows its origin'))
        ledger.grant_knowledge('ana', 'blue_hidden', tick=0, source_type='observation')
        ledger.grant_knowledge('bea', 'red_hidden', tick=0, source_type='observation')
        packet = BeatPacketCompiler(world, ledger, junctions={}).compile(
            {'beat_id': 'keys', 'scene_location': 'hall', 'primary_character': 'ana',
             'reader_reveals': ['The hall clock stops.']})
        request = ProseRewriteRequest.from_beat_packet(packet, original_text='Ana waits.')
        self.assertEqual(request.character_inventory, {'ana': ['blue_key'], 'bea': ['red_key']})
        self.assertEqual(request.active_props, {'red_key': 'broken'})
        self.assertEqual(request.character_epistemic_scope, {'ana': ['blue_hidden'], 'bea': ['red_hidden']})
        self.assertEqual(request.reader_reveals, ['The hall clock stops.'])
        prompt = PromptAssembler.assemble(
            request, ProseDiagnosticReport(span_id=request.target_span_id), STANDARD_DRAMATIC, [], [])
        self.assertIn('ana holds: blue_key', prompt)
        self.assertIn('bea knows: red_hidden', prompt)
        self.assertNotIn('ana knows: red_hidden', prompt)
        reader = prompt.split('READER REVEALS', 1)[1]
        self.assertIn('The hall clock stops.', reader)
        self.assertNotIn('blue_hidden', reader)

    def test_screenplay_markdown_rendering(self):
        rec = self.sequencer.execute_beat("beat_01_francine_kitchen_briefing")
        packet = self.compiler.compile(rec)
        md = packet.to_screenplay_markdown()

        self.assertIn("### INT. KITCHEN - CONTINUOUS", md)
        self.assertIn("<!-- BEAT_ID: beat_01_francine_kitchen_briefing", md)
        self.assertIn("<!-- AESTHETIC_TAGS: [suburban_authority, casserole_briefing", md)
        self.assertIn("FRANCINE", md)
        self.assertIn("(shouting up the stairwell)", md)
        self.assertIn("Rainee, let's go!", md)

    def test_full_scenario_manifest_and_raw_script(self):
        # Execute all 10 beats sequentially
        while not self.sequencer.is_finished():
            eligible = self.sequencer.get_eligible_beats()
            self.assertTrue(len(eligible) > 0, "Sequencer stalled before finishing.")
            self.sequencer.execute_beat(eligible[0].id)

        self.assertEqual(len(self.sequencer.execution_log), 10)

        # Compile all 10 packets
        packets = self.compiler.compile_all(self.sequencer.execution_log)
        self.assertEqual(len(packets), 10)

        # Verify sensory links on Beat 8 (Haley outside bathroom)
        beat_8 = packets[7]
        self.assertEqual(beat_8.beat_id, "beat_08_haley_scent_discovery")
        self.assertIn("dead_flower_shop_clash", beat_8.aesthetic_tags)

        # Export test manifest and raw script
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "spring_breakup_beat_manifest.json"
            raw_script_path = Path(tmp) / "spring_breakup_raw_script.md"
            self.compiler.export_manifest(packets, manifest_path)
            raw_md = self.compiler.export_raw_script(packets, raw_script_path)
            self.assertEqual(raw_script_path.read_text(encoding="utf-8"), raw_md)
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest_data["beat_count"], 10)
        self.assertEqual(len(manifest_data["packets"]), 10)

        # Verify raw script has all dialogue turns and clean markdown
        self.assertIn("Ah, the ancient art of ancestral toot-massage.", raw_md)
        self.assertIn("Mom? Are you farting up there? It smells like a flower shop died!", raw_md)
        self.assertIn("—OH!", raw_md)


if __name__ == "__main__":
    unittest.main()
