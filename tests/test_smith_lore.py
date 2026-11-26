"""
Regression tests for the canonical Ling-vs-Smith divergence.

The model imports American Dad! canon from the web ("Francine Smith", "Stan Smith").
This story deliberately diverges: Francine never married Stan, he dumped her, and the
household is strictly Ling. The rules must reject the imported canon while allowing
canonical references to Stan as the ex who dumped her.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prose_engine.invariant_gate import InvariantGate
from prose_engine.linter import AntiAILinter
from prose_engine.models import ProseRewriteRequest
from prose_engine.voice.world_state import WorldState
from story_graph.ontology import OntologyGraph


BURSTY = (
    "The kitchen smelled of coffee and rain. She walked to the window, slowly, and "
    "looked out at the empty street. A car passed. The dog barked twice, then stopped. "
    "Nobody answered the door. Outside, the wind pushed a paper cup along the gutter "
    "until it lodged beneath a parked bicycle. She poured another cup and sat down. "
    "It was going to be one of those mornings. The clock above the stove ticked."
)

CANON_LINES = [
    "Please—they'll be relieved I didn't marry Stan, and look at you!",
    "Francine never married Stan; he dumped her before any wedding.",
    "Stan dumped her, so she kept the Ling name.",
    "She didn't take the Smith name.",
    "Stan was never her husband.",
]

IMPORTED_CANON = [
    "Stan Smith walked in from the garage and kissed Francine.",
    "Francine Smith smiled at the stove.",
    "Mrs. Smith poured the coffee.",
    "The Smiths arrived at noon.",
    "The Smith house stood empty.",
    "Smith handed her the keys.",
    "Haley Smith looked up from her phone.",
]


def rewrite_request(onto: OntologyGraph) -> ProseRewriteRequest:
    return ProseRewriteRequest(
        request_id="req_smith",
        project_id="noir_foxy",
        document_id="doc_smith",
        base_revision=1,
        target_span_id="span_smith",
        original_text="",
        ontological_invariants=onto.get_summary_invariants(),
        negative_constraints=onto.hard_negative_rules,
        character_morph_permissions=onto.get_character_morph_permissions(),
    )


class TestSmithLore(unittest.TestCase):
    def setUp(self) -> None:
        self.onto = OntologyGraph.create_canonical_foxy_mo2()
        self.request = rewrite_request(self.onto)
        self.linter = AntiAILinter()
        self.world = WorldState.load(ROOT / "books" / "world_state.json")

    def test_divergence_is_recorded_as_world_lore(self):
        self.assertEqual(len(self.onto.canon_divergences), 1)
        lore = self.onto.canon_divergences[0]
        self.assertEqual(lore["source_show"], "American Dad!")
        self.assertIn("dumped her", lore["story_canon"])
        self.assertIn("Smith", lore["imported_canon"])
        self.assertIn("dumped her", self.onto.get_summary_invariants()[0])

        smith_rule = next(r for r in self.onto.hard_negative_rules if r["id"] == "rule_no_smith_surname")
        self.assertTrue(smith_rule["allow_negated"])

    def test_invariant_gate_allows_canonical_negations(self):
        for text in CANON_LINES:
            with self.subTest(text=text):
                ok, violations, _ = InvariantGate.audit_rewrite(text, self.request)
                self.assertTrue(ok, f"canon line rejected: {text} -> {violations}")

    def test_invariant_gate_rejects_imported_canon(self):
        for text in IMPORTED_CANON:
            with self.subTest(text=text):
                ok, violations, _ = InvariantGate.audit_rewrite(text, self.request)
                self.assertFalse(ok, f"imported canon accepted: {text}")
                self.assertTrue(
                    any("smith" in v.lower() or "stan" in v.lower() for v in violations),
                    violations,
                )

    def test_world_state_allows_canon_and_flags_imports(self):
        for text in CANON_LINES:
            with self.subTest(text=text):
                self.assertEqual(self.world.violations(text), [], text)
        for text in IMPORTED_CANON:
            with self.subTest(text=text):
                self.assertTrue(self.world.violations(text), text)

    def test_canon_guard_catches_unambiguous_smith_forms_and_linter_stays_stylistic(self):
        from prose_engine.canon_guard import canon_conflicts

        for text in [
            "Stan Smith walked in.",
            "Francine Smith smiled.",
            "Mrs. Smith poured the coffee.",
            "The Smiths arrived at noon.",
            "The Smith house stood empty.",
        ]:
            with self.subTest(text=text):
                conflicts = canon_conflicts(text, episode_id="spring-break")
                self.assertTrue(
                    any(f.code == "SHOW_IMPORT_BLEED" for f in conflicts),
                    conflicts,
                )
        # AntiAILinter handles style/tells only and must not false-positive on negated lore.
        negated_smith = f"Francine never took the Smith name. {BURSTY}"
        report = self.linter.lint(negated_smith, burstiness_threshold=0.0)
        self.assertTrue(report.passed, [(v.category, v.matched_text) for v in report.violations])
        self.assertEqual(canon_conflicts("Francine never took the Smith name.", episode_id="spring-break"), [])

    def test_linter_allows_canonical_negation(self):
        report = self.linter.lint(f"I didn't marry Stan. {BURSTY}", burstiness_threshold=0.0)
        self.assertTrue(
            report.passed,
            [(v.category, v.matched_text) for v in report.violations],
        )

    def test_patriarch_simile_is_allowed(self):
        text = "Nothing to see here, just Mom cosplaying as a cartoon dad with a Kardashian rear."
        ok, violations, _ = InvariantGate.audit_rewrite(text, self.request)
        self.assertTrue(ok, violations)

    def test_jeff_husband_line_is_rejected(self):
        text = "just because you inherited your husband Jeff's ass is no reason to be catty."
        ok, violations, _ = InvariantGate.audit_rewrite(text, self.request)
        self.assertFalse(ok)
        self.assertTrue(any("husband" in v.lower() for v in violations), violations)


if __name__ == "__main__":
    unittest.main()
