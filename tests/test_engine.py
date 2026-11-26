"""Tests for the standalone prose engine."""

import json
import tempfile
import unittest
from pathlib import Path

from prose_engine.conditioner import apply_proposals, paragraph_spans, plan_conditioning
from prose_engine.corpus import (
    corpus_index,
    derive_style_profile,
    load_corpus,
    reference_passages,
)
from prose_engine.diagnostics import ProseDiagnosticsAnalyzer
from prose_engine.style_engine import STANDARD_DRAMATIC, StyleProfileRepository

GOOD = (
    "The coffee was cold and the smoke hung in the neon light. She waited a long time."
)
BAD = "Mara noticed the door was open. She felt a chill. She saw the table. She heard the wind."
MONOTONE = (
    "The man walked into the room. He sat down in the chair. He stood up again. "
    "He walked out of the room. He came back later."
)
WRAPPER = "A cold room. A long night."


class AppendingProvider:
    """Returns a genuine rewrite that keeps the facts."""

    model_name = "appending"

    def generate_rewrite(self, request, prompt):  # noqa: ARG002
        return "Mara stood in the doorway. A chill crossed her back. The floorboards ticked."


class OversizedProvider:
    model_name = "oversized"

    def generate_rewrite(self, request, prompt):  # noqa: ARG002
        return (
            "A woman entered the parlor and chose the hard chair. She rose, crossed the floor, "
            "and stood at the window. Later she returned with a lamp and a folded coat. The house "
            "settled around her, board by board, and she listened to it the way you listen to a "
            "stranger breathing in the next room, patient and unafraid, until the clock struck."
        )


class EmptyProvider:
    model_name = "empty"

    def generate_rewrite(self, request, prompt):  # noqa: ARG002
        return ""


class TestDiagnostics(unittest.TestCase):
    def test_filter_words_are_flagged(self):
        report = ProseDiagnosticsAnalyzer.analyze("She noticed the door. He felt a wave of dread.")
        self.assertGreater(report.filter_word_count, 0)
        self.assertIn("Filter words", report.warnings[0])

    def test_clean_prose_has_no_warnings(self):
        report = ProseDiagnosticsAnalyzer.analyze(GOOD)
        self.assertEqual(report.warnings, [])


class TestStyleProfiles(unittest.TestCase):
    def test_builtin_profiles(self):
        repository = StyleProfileRepository()
        self.assertIn("standard_dramatic", repository.list_profiles())
        self.assertIn("noir_detective", repository.list_profiles())


class TestParagraphs(unittest.TestCase):
    def test_paragraph_spans_cover_blank_line_groups(self):
        text = f"{WRAPPER}\n\n{BAD}\n\n{GOOD}\n"
        spans = paragraph_spans(text)
        self.assertEqual(len(spans), 3)
        self.assertEqual(text[spans[1][0] : spans[1][1]], BAD)


class TestConditioning(unittest.TestCase):
    def test_plans_and_applies_only_the_bad_paragraph(self):
        text = f"{GOOD}\n\n{BAD}\n\n{WRAPPER}\n"
        proposals = plan_conditioning(text, AppendingProvider(), STANDARD_DRAMATIC)

        self.assertEqual(len(proposals), 1)
        self.assertTrue(proposals[0].accepted, proposals[0].reason)
        self.assertIn("Filter words", "; ".join(proposals[0].warnings))

        updated, applied = apply_proposals(text, proposals)
        self.assertEqual(applied, 1)
        self.assertIn(GOOD, updated)
        self.assertIn(WRAPPER, updated)
        self.assertIn("The floorboards ticked.", updated)
        self.assertNotIn("She noticed", updated)

    def test_rejects_oversized_rewrite(self):
        proposals = plan_conditioning(f"{MONOTONE}\n", OversizedProvider(), STANDARD_DRAMATIC)
        self.assertEqual(len(proposals), 1)
        self.assertFalse(proposals[0].accepted)
        self.assertIn("length ratio", proposals[0].reason)

    def test_rejects_empty_rewrite(self):
        proposals = plan_conditioning(f"{BAD}\n", EmptyProvider(), STANDARD_DRAMATIC)
        self.assertFalse(proposals[0].accepted)
        self.assertIn("empty", proposals[0].reason)


def _write_corpus(root: Path) -> None:
    (root / "text").mkdir(parents=True)
    (root / "text" / "alpha.txt").write_text(GOOD + "\n\n" + BAD + "\n", encoding="utf-8")
    (root / "text" / "beta.txt").write_text(GOOD + "\n\n" + GOOD + "\n", encoding="utf-8")
    manifest = {
        "books": [
            {"slug": "alpha", "title": "Alpha", "author": "", "file": "text/alpha.txt", "pages": 2},
            {"slug": "beta", "title": "Beta", "author": "", "file": "text/beta.txt", "pages": 2},
        ]
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class TestCorpus(unittest.TestCase):
    def test_load_measure_and_derive_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "books"
            _write_corpus(root)

            books = load_corpus(root)
            self.assertEqual([book.slug for book in books], ["alpha", "beta"])

            index = corpus_index(books)
            self.assertEqual(index["aggregate"]["books"], 2)
            self.assertGreater(index["aggregate"]["words"], 0)

            profile = derive_style_profile(books, profile_id="test", name="Test")
            self.assertGreaterEqual(profile.target_cadence_burstiness, 3.5)
            self.assertLessEqual(profile.target_cadence_burstiness, 8.0)

            passages = reference_passages(books, profile_id="test", count=2)
            self.assertLessEqual(len(passages), 2)
            for passage in passages:
                self.assertEqual(passage.profile_id, "test")


if __name__ == "__main__":
    unittest.main()
