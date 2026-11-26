"""S2 contracts: author-anchored voice, no book text in prompts, provider routing."""

import unittest
from pathlib import Path

from prose_engine.guards import reference_copies
from prose_engine.providers.router import route
from prose_engine.voice.author_voice import block


class AuthorVoiceTests(unittest.TestCase):
    def test_block_has_rules_and_no_book_text(self):
        text = block("INT. BATHROOM — CONTINUOUS")
        self.assertIn("STYLE CARD", text)
        self.assertIn("COMEDY MECHANICS", text)
        books = [path.read_text(encoding="utf-8", errors="ignore") for path in Path("books/text").glob("*.txt")]
        self.assertEqual(reference_copies(text, books, 6), [], "author voice block must never copy book text")


class RouterTests(unittest.TestCase):
    def test_variation_needs_a_direction_for_frontier(self):
        self.assertEqual(route("variation", has_direction=False).provider, "local")
        self.assertEqual(route("variation", has_direction=True).provider, "deepseek")

    def test_budget_exhaustion_falls_back(self):
        self.assertEqual(route("variation", has_direction=True, budget_exhausted=True).provider, "local")

    def test_flagging_is_local(self):
        self.assertEqual(route("flag").provider, "local")


if __name__ == "__main__":
    unittest.main()
