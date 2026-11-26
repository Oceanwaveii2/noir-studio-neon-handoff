"""Unit tests for the accumulative World Law, Character Mind, and StateCompiler system."""
from __future__ import annotations

import sqlite3
import unittest

from story_graph.canon_models import (
    CandidateClaim,
    CharacterMemory,
    StateDelta,
    StoryCoord,
)
from story_graph.seeds.afm_seed import DEFAULT_AFM_UNIVERSE, seed_afm_universe
from story_graph.state_compiler import (
    StateCompiler,
    append_delta,
    list_proposals,
    propose_canon_change,
    record_memory,
    resolve_proposal,
    retire_delta,
)
from story_graph.state_validator import validate_claims, validate_text


class StateCompilerTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        seed_afm_universe(self.conn, universe_id=DEFAULT_AFM_UNIVERSE)
        self.compiler = StateCompiler(self.conn)

    def tearDown(self):
        self.conn.close()

    def _coord(self, episode: str, pos: float, beat: int = 0, branch: str = "main") -> StoryCoord:
        return StoryCoord(
            universe_id=DEFAULT_AFM_UNIVERSE,
            branch=branch,
            episode_id=episode,
            episode_position=pos,
            beat=beat,
        )

    def test_accumulative_haley_jeff_timeline(self):
        # 1. Spring Break-Up (pos=10.0): boyfriend valid, husband Jeff = ERA_ANACHRONISM, fox tail = conflict
        sb = self.compiler.compile_state(self._coord("spring-break", 10.0, 0))
        self.assertEqual(sb.relationships[("haley", "jeff")]["status"], "dating")
        self.assertEqual(sb.characters["haley"]["biology_stage"], "dormant_hybrid")

        ok_boyfriend = validate_text("Haley inherited her boyfriend Jeff's flat rear.", sb)
        self.assertFalse(any(f.status == "conflict" for f in ok_boyfriend))

        err_husband = validate_text("Haley waited for her husband Jeff.", sb)
        self.assertTrue(any(f.code == "ERA_ANACHRONISM" for f in err_husband))

        tease_husband = validate_text("Rainee joked about her husband Jeff.", sb, assertion_default="dialogue_teasing")
        self.assertFalse(any(f.status == "conflict" for f in tease_husband))
        self.assertTrue(any(f.code == "TEASING_DIALOGUE_EXEMPT" for f in tease_husband))

        err_tail = validate_text("Haley flicks her tail nervously.", sb)
        self.assertTrue(any(f.code == "BIOLOGY_ANACHRONISM" for f in err_tail))

        # 2. Hot Scoomp pre-awakening (pos=20.0, beat=0): married -> husband Jeff PASSES
        hs_pre = self.compiler.compile_state(self._coord("hot-scoomp", 20.0, 0))
        self.assertEqual(hs_pre.relationships[("haley", "jeff")]["status"], "married")
        res_hs_pre = validate_text("Haley avoided her husband Jeff before gym class.", hs_pre)
        self.assertFalse(any(f.status == "conflict" for f in res_hs_pre))

        # 3. Hot Scoomp awakened (pos=20.0, beat=2): fox traits PASS, attraction to Jeff CONFLICTS, Holly affair present
        hs_awake = self.compiler.compile_state(self._coord("hot-scoomp", 20.0, 2))
        self.assertEqual(hs_awake.characters["haley"]["biology_stage"], "awakened_fox")
        self.assertEqual(hs_awake.relationships[("haley", "holly_graham")]["status"], "affair_cheating")

        res_awake_tail = validate_text("Haley flicks her tail beside Holly.", hs_awake)
        self.assertFalse(any(f.status == "conflict" for f in res_awake_tail))

        err_desire_jeff = validate_text("Haley eagerly kissed Jeff in the hallway.", hs_awake)
        self.assertTrue(any(f.code == "CHARACTER_STATE_CONFLICT" for f in err_desire_jeff))

        # 4. Tapped Out (pos=30.0): Jeff acquires Jess device -> intimacy as Jess SUPPORTED
        to = self.compiler.compile_state(self._coord("tapped-out", 30.0, 0))
        self.assertIn("jess_intimacy_device", to.characters["jeff"]["devices"])
        jess_claim = CandidateClaim(
            claim_id="c-jess",
            coord=to.coord,
            block_id="b1",
            span_start=0,
            span_end=20,
            excerpt="Jeff used the device to become Jess for Haley.",
            assertion_class="narration_fact",
            subject_id="jeff",
            predicate="intimacy_as_jess",
            value_or_target="jess",
        )
        res_jess = validate_claims([jess_claim], to)
        self.assertEqual(res_jess[0].code, "DEVICE_SALVAGE_SUPPORTED")
        self.assertEqual(res_jess[0].status, "supported")

    def test_universal_biology_vs_soft_tendency_and_noir_exception(self):
        sb = self.compiler.compile_state(self._coord("spring-break", 10.0, 0))
        # Hard biological rule: foxes cannot have sons
        son_err = validate_text("Rainee gave birth to a son in secrecy.", sb)
        self.assertTrue(any(f.rule_id == "fox_no_sons" and f.status == "conflict" for f in son_err))

        # Soft attraction tendency: Noir has trait exception; Stella does not
        noir_claim = CandidateClaim(
            claim_id="c-noir",
            coord=sb.coord,
            block_id="b1",
            span_start=0,
            span_end=30,
            excerpt="Noir dated a guy once alongside her wives and girlfriends.",
            assertion_class="narration_fact",
            subject_id="noir",
            predicate="male_attraction",
            value_or_target="man",
        )
        stella_claim = CandidateClaim(
            claim_id="c-stella",
            coord=sb.coord,
            block_id="b2",
            span_start=0,
            span_end=20,
            excerpt="Stella pursued a man.",
            assertion_class="narration_fact",
            subject_id="stella",
            predicate="male_attraction",
            value_or_target="man",
        )
        res_noir = validate_claims([noir_claim], sb)
        self.assertEqual(res_noir[0].code, "SOFT_LAW_EXCEPTION_GRANTED")
        self.assertEqual(res_noir[0].status, "supported")

        res_stella = validate_claims([stella_claim], sb)
        self.assertEqual(res_stella[0].code, "SOFT_TENDENCY_UNEXPLAINED")
        self.assertEqual(res_stella[0].severity, "warning")

    def test_import_bleed_guard_exempts_negation_and_broadcast_quote(self):
        sb = self.compiler.compile_state(self._coord("spring-break", 10.0, 0))
        bleed = validate_text("Francine Smith poured coffee in the Smith kitchen.", sb)
        self.assertGreaterEqual(len([f for f in bleed if f.code == "SHOW_IMPORT_BLEED"]), 2)

        negated = validate_text("Francine never took the Smith name and never married Stan.", sb)
        self.assertEqual(negated, [])

        quoted = validate_text(
            "INT. SMITH KITCHEN — 7:31 A.M.",
            sb,
            source_origin="broadcast_quote_fixture",
        )
        self.assertEqual(quoted, [])

    def test_branch_inheritance_and_viewpoint_isolation(self):
        self.conn.executescript(
            """
            CREATE TABLE branches(id TEXT PRIMARY KEY, parent TEXT, fork_episode TEXT, fork_beat INTEGER);
            CREATE TABLE episodes(id TEXT PRIMARY KEY, title TEXT NOT NULL, branch TEXT NOT NULL, position INTEGER NOT NULL);
            INSERT INTO branches VALUES ('main', NULL, NULL, NULL);
            INSERT INTO episodes VALUES ('spring-break', 'Spring Break', 'main', 10);
            INSERT INTO episodes VALUES ('hot-scoomp', 'Hot Scoomp', 'main', 20);
            INSERT INTO branches VALUES ('relapse', 'main', 'spring-break', 2);
            INSERT INTO branches VALUES ('clothes', 'main', 'spring-break', 2);
            """
        )
        record_memory(
            self.conn,
            CharacterMemory(
                memory_id="mem_clothes_secret",
                universe_id=DEFAULT_AFM_UNIVERSE,
                owner_scope="personal",
                owner_id="rainee",
                subject_id="clothes",
                predicate="secret_location",
                object_value="red sedan trunk",
                branch="clothes",
                episode_pos=10.0,
                beat=3,
            ),
        )
        append_delta(
            self.conn,
            StateDelta(
                delta_id="d_clothes_reveal",
                universe_id=DEFAULT_AFM_UNIVERSE,
                branch="clothes",
                episode_id="spring-break",
                episode_pos=10.0,
                beat=3,
                seq=1,
                op="GRANT_KNOWLEDGE",
                subject_id="rainee",
                payload={"fact": "clothes trunk stash"},
            ),
        )
        # Sibling branch 'relapse' must NOT see 'clothes' branch state or memory
        relapse_state = self.compiler.compile_state(
            self._coord("spring-break", 10.0, 5, branch="relapse"),
            viewpoint="rainee",
        )
        self.assertNotIn("clothes trunk stash", relapse_state.characters["rainee"]["known_facts"])
        # Private Rainee memory hidden when compiling for Haley viewpoint even on 'clothes'
        clothes_haley = self.compiler.compile_state(
            self._coord("spring-break", 10.0, 5, branch="clothes"),
            viewpoint="haley",
        )
        self.assertTrue(any(h["object_value"] == "red sedan trunk" for h in clothes_haley.hidden_facts))

    def test_canon_proposal_review_and_delta_retire_undo(self):
        coord = self._coord("spring-break", 10.0, 1)
        before = self.compiler.compile_state(coord, use_checkpoint=True)
        pid = propose_canon_change(
            self.conn,
            coord,
            kind="state_delta",
            payload={
                "op": "GRANT_KNOWLEDGE",
                "subject_id": "haley",
                "payload": {"fact": "noticed nurse badge"},
            },
            rationale="Haley spotted Franny badge in beat 1.",
        )
        self.assertEqual(len(list_proposals(self.conn, DEFAULT_AFM_UNIVERSE, status="pending")), 1)
        still_before = self.compiler.compile_state(coord)
        self.assertEqual(still_before.state_digest, before.state_digest)

        accepted = resolve_proposal(self.conn, pid, "accepted", "Author")
        after = self.compiler.compile_state(coord)
        self.assertNotEqual(after.state_digest, before.state_digest)
        self.assertIn("noticed nurse badge", after.characters["haley"]["known_facts"])

        retire_delta(self.conn, accepted["applied_id"], retired=True)
        undone = self.compiler.compile_state(coord)
        self.assertNotIn("noticed nurse badge", undone.characters["haley"]["known_facts"])


if __name__ == "__main__":
    unittest.main()
