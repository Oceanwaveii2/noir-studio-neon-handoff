"""Influence contract tests."""

import unittest

from prose_engine.influence import Influence, parse_level, select


def scored(book: str, n: int, base: float = 1.0):
    return [(base - i * 0.01, f"{book}-{i}", {"book": book}) for i in range(n)]


class InfluenceTests(unittest.TestCase):
    def test_level_names_and_numbers(self):
        self.assertEqual(parse_level("off"), 0)
        self.assertEqual(parse_level("dominant"), 4)
        self.assertEqual(parse_level(3), 3)
        with self.assertRaises(ValueError):
            parse_level("loud")

    def test_off_excludes_book(self):
        pool = scored("big", 20) + scored("small", 5)
        inf = Influence(levels={"big": 0})
        picks = select(pool, 6, inf)
        self.assertTrue(picks)
        self.assertTrue(all(item[2]["book"] == "small" for item in picks))

    def test_balanced_does_not_let_a_big_book_take_everything(self):
        pool = scored("big", 60) + scored("small", 10)
        picks = select(pool, 8, Influence(mode="balanced"))
        books = [item[2]["book"] for item in picks]
        self.assertGreaterEqual(books.count("small"), 3)
        self.assertLessEqual(books.count("big"), 5)

    def test_strong_level_gets_more_picks(self):
        pool = scored("a", 30) + scored("b", 30)
        inf = Influence(levels={"a": 2, "b": 4}, mode="balanced")
        picks = select(pool, 12, inf)
        books = [item[2]["book"] for item in picks]
        self.assertGreater(books.count("b"), books.count("a"))

    def test_volume_mode_keeps_size_bias_but_respects_weight(self):
        pool = scored("big", 40, base=1.0) + scored("small", 4, base=0.9)
        picks = select(pool, 10, Influence(mode="volume"))
        self.assertTrue(all(item[2]["book"] == "big" for item in picks))
        inf = Influence(levels={"big": 1, "small": 4}, mode="volume")
        picks = select(pool, 10, inf)
        self.assertTrue(any(item[2]["book"] == "small" for item in picks))

    def test_k_larger_than_pool(self):
        pool = scored("a", 2)
        picks = select(pool, 10, Influence())
        self.assertEqual(len(picks), 2)


if __name__ == "__main__":
    unittest.main()
