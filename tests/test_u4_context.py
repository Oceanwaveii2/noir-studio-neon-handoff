import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from prose_engine.voice import vary
from story_graph.character_forms import AFM_JUNCTIONS, CharacterForm, CharacterJunction, FormLink
from story_graph.compiler import BeatPacketCompiler
from story_graph.dag import CausalDAG, BeatNode, BeatSequencer
from story_graph.epistemic import EpistemicLedger, Fact
from story_graph.models import CharacterState, Location, Portal, PortalState, Transaction
from story_graph.world_state import StoryWorldState


class CharacterJunctionTests(unittest.TestCase):
    def test_five_groups_have_separate_stable_ports(self):
        self.assertEqual(set(AFM_JUNCTIONS), {"roger", "francine", "rainee", "stella", "haley"})
        ports = set()
        for cid, junction in AFM_JUNCTIONS.items():
            group = junction.project(planning=True)
            self.assertEqual(group["junction_id"], f"character:{cid}")
            self.assertGreater(len(group["forms"]), 1)
            for form in group["forms"]:
                self.assertNotIn(form["port_id"], ports)
                ports.add(form["port_id"])
            self.assertEqual(len(junction.project()["forms"]), 1)

    def test_ordered_stage_links_round_trip_and_future_context_is_excluded(self):
        stella = AFM_JUNCTIONS["stella"]
        base = replace(stella.forms[0], link=FormLink("digital_mind", "base-mind"))
        stage = CharacterForm("test-stage", "Synthetic test stage", "stage", after=base.id,
                              link=FormLink("super_character", "stage-character"))
        end = replace(stella.forms[-1], after=stage.id)
        original = CharacterJunction("stella", (base, stage, end))
        planning = original.project(planning=True)
        decoded = CharacterJunction.from_record(json.loads(json.dumps(planning)))
        self.assertEqual(original, decoded)
        self.assertEqual(decoded.project(approved=[end.id], active=end.id)["forms"][0]["status"], "active")
        active = decoded.project(approved=[stage.id, end.id], active=stage.id)
        self.assertEqual(active["character_id"], "stella")
        self.assertEqual([r["status"] for r in active["forms"]], ["available", "active", "available"])
        self.assertEqual(active["forms"][0]["link"]["node_id"], "base-mind")
        self.assertEqual(active["forms"][1]["link"]["node_id"], "stage-character")
        self.assertEqual(len(AFM_JUNCTIONS["haley"].project(active="awakened_haley_fox")["forms"]), 1)

    def test_invalid_predecessor_and_link_are_rejected(self):
        with self.assertRaises(ValueError):
            CharacterJunction("stella", (AFM_JUNCTIONS["stella"].forms[0],
                                         CharacterForm("stage", "Stage", "stage", "unseen")))
        with self.assertRaises(ValueError):
            FormLink("manuscript", "unrelated-node")


class HistoricalContextTests(unittest.TestCase):
    def test_compiling_after_later_move_and_reveal_preserves_earlier_context(self):
        world = StoryWorldState()
        world.add_location(Location("hall", "Hall"))
        world.add_location(Location("kitchen", "Kitchen"))
        world.add_portal(Portal("door", "Door", "hall", "kitchen", state=PortalState.OPEN))
        world.add_character(CharacterState("haley", "Haley", "hall"))
        ledger = EpistemicLedger()
        ledger.register_fact(Fact("secret", "Later reveal", ["password"], origin_tick=2, is_private=True))
        ledger.register_fact(Fact("home", "Home", ["home"]))
        ledger.grant_knowledge("haley", "home", "observation", 0)
        dag = CausalDAG()
        dag.add_beat(BeatNode("before", "Before", "scene", "Waiting", "haley"))
        dag.add_beat(BeatNode("after", "After", "scene", "Moving", "haley",
                              dependencies=["before"], transactions=[Transaction("move", "haley", "kitchen")]))
        sequencer = BeatSequencer(dag, world)
        before = sequencer.execute_beat("before")
        after = sequencer.execute_beat("after")
        self.assertLess(before["tick"], after["tick"])
        ledger.grant_knowledge("haley", "secret", "speech", after["tick"])
        ledger.grant_knowledge("haley", "home", "observation", after["tick"], certainty=0.2)
        ledger = self._round_trip(ledger)
        earlier, later = BeatPacketCompiler(world, ledger).compile_all([before, after])
        self.assertEqual(earlier.slugline, "INT. HALL - CONTINUOUS")
        self.assertEqual(later.slugline, "INT. KITCHEN - CONTINUOUS")
        self.assertNotEqual(earlier.world_snapshot_sha256, later.world_snapshot_sha256)
        self.assertEqual(earlier.epistemic_context["haley"], ["home"])
        self.assertEqual(later.epistemic_context["haley"], ["secret"])
        self.assertEqual(ledger.audit_text_for_leaks("haley", "password", before["tick"]), [("secret", "password")])
        self.assertFalse(ledger.audit_text_for_leaks("haley", "password", after["tick"]))
        with self.assertRaisesRegex(ValueError, "requires its recorded world snapshot"):
            BeatPacketCompiler(world).compile({k: v for k, v in before.items() if k != "world_after"})

    def _round_trip(self, ledger):
        restored = EpistemicLedger()
        restored.restore(json.loads(json.dumps(ledger.snapshot())))
        return restored


class BeatAtomicityTests(unittest.TestCase):
    def test_failed_second_transaction_does_not_apply_first(self):
        world = StoryWorldState()
        world.add_location(Location("hall", "Hall"))
        world.add_location(Location("kitchen", "Kitchen"))
        world.add_portal(Portal("door", "Door", "hall", "kitchen", state=PortalState.OPEN))
        world.add_character(CharacterState("haley", "Haley", "hall"))
        dag = CausalDAG()
        dag.add_beat(BeatNode("partial", "Partial", "scene", "Move and take", "haley",
                             transactions=[Transaction("move", "haley", "kitchen"),
                                           Transaction("take", "haley", "missing")]))
        sequence = BeatSequencer(dag, world)
        original = world.snapshot()
        with self.assertRaisesRegex(RuntimeError, "missing"):
            sequence.execute_beat("partial")
        self.assertEqual(world.snapshot(), original)
        self.assertEqual(world.transaction_history, [])
        self.assertFalse(sequence.execution_log)
        self.assertFalse(sequence.completed_beats)


class VariationTests(unittest.TestCase):
    def test_new_staging_issue_and_duplicate_are_rejected_without_encoder(self):
        class House:
            def check_scene(self, chunks):
                return ["impossible room move"] if "Wall jump." in chunks else []

        class Provider:
            def __init__(self):
                self.takes = iter(["Wall jump.", "A quiet pause.", "A QUIET PAUSE!", "Footsteps fade.", "Rain begins."])

            def generate_rewrite(self, request, prompt):
                return next(self.takes)

        def unavailable(text):
            raise RuntimeError("encoder unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.md"
            path.write_text("The room settled.\n\nAnother paragraph follows.", encoding="utf-8")
            with (patch.object(vary.House, "load", return_value=House()),
                  patch.object(vary.WorldState, "load", return_value=None),
                  patch.object(vary, "build_prompt", return_value="test"),
                  patch.object(vary, "adversarial_check", side_effect=lambda *_: [])):
                result = vary.run(Provider(), path, 0, "test", n=5, draws=1, encode=unavailable)
                repeated = vary.run(Provider(), path, 0, "test", n=5, draws=1)
        self.assertEqual(result, repeated)
        self.assertEqual(result["distinctness"], "lexical_fallback")
        self.assertEqual(result["selected"], 3)
        self.assertEqual(result["takes"][0]["issues"], ["staging: impossible room move"])
        self.assertEqual([r["chosen"] for r in result["takes"][1:3]], [True, False])
