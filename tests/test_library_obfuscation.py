"""Verify 190-book title obfuscation and copyright/publisher excerpt sanitization."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from prose_engine.scoped_references import sanitize_reference_excerpt
from tools.book_ingest import ingest_incoming


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOKS_ROOT = REPO_ROOT / 'books'


class LibraryObfuscationTests(unittest.TestCase):
    def test_obscured_titles_covers_all_manifest_books_uniquely(self):
        manifest = json.loads((BOOKS_ROOT / 'manifest.json').read_text(encoding='utf-8'))
        obscured = json.loads((BOOKS_ROOT / 'obscured_titles.json').read_text(encoding='utf-8'))
        books = manifest.get('books', [])
        mapping = obscured.get('books', {})
        self.assertEqual(len(mapping), len(books))
        seen_titles = set()
        seen_aliases = set()
        for entry in books:
            slug = entry['slug']
            self.assertIn(slug, mapping)
            rec = mapping[slug]
            self.assertTrue(rec['alias_id'])
            self.assertTrue(rec['obscured_title'])
            self.assertTrue(rec.get('book_type'))
            self.assertTrue(rec.get('craft_tags'))
            self.assertTrue(rec.get('prose_usefulness'))
            self.assertNotEqual(rec['obscured_title'].casefold(), entry.get('title', '').casefold())
            self.assertNotIn(rec['obscured_title'], seen_titles)
            self.assertNotIn(rec['alias_id'], seen_aliases)
            seen_titles.add(rec['obscured_title'])
            seen_aliases.add(rec['alias_id'])

    def test_sanitize_reference_excerpt_strips_copyright_and_publisher_lines(self):
        raw = (
            "RIVERHEAD BOOKS\n"
            "An imprint of Penguin Random House LLC\n"
            "Copyright © 2021 by Example Author. All rights reserved.\n"
            "ISBN 978-0-00-000000-0\n"
            "She stepped onto the porch and let the screen door bang shut behind her."
        )
        cleaned = sanitize_reference_excerpt(raw)
        self.assertNotIn('RIVERHEAD', cleaned)
        self.assertNotIn('Penguin Random House', cleaned)
        self.assertNotIn('Copyright', cleaned)
        self.assertNotIn('ISBN', cleaned)
        self.assertEqual(
            cleaned,
            'She stepped onto the porch and let the screen door bang shut behind her.',
        )

    def test_ingest_incoming_automatically_sanitizes_and_obscures_new_books(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            incoming = root / 'incoming'
            books = root / 'books'
            incoming.mkdir()
            body = ' '.join(['Comedy banter escalates across the parlor room.'] * 120)
            (incoming / 'curvy_slapstick_test.txt').write_text(
                'RIVERHEAD BOOKS\n'
                'Copyright © 2024 Example Press. All rights reserved.\n'
                'ISBN 978-1-23456-789-0\n'
                + body,
                encoding='utf-8',
            )
            entries = ingest_incoming(incoming, books, force=True)
            self.assertEqual(len(entries), 1)
            ingested_txt = (books / 'text' / 'curvy_slapstick_test.txt').read_text(encoding='utf-8')
            self.assertNotIn('RIVERHEAD BOOKS', ingested_txt)
            self.assertNotIn('Copyright', ingested_txt)
            self.assertNotIn('ISBN', ingested_txt)
            obscured = json.loads((books / 'obscured_titles.json').read_text(encoding='utf-8'))
            rec = obscured['books']['curvy_slapstick_test']
            self.assertEqual(rec['book_type'], 'curvy_glam_romance')
            self.assertTrue(rec['alias_id'].startswith('folio_curvy_glam_romance_'))
            self.assertTrue(rec['obscured_title'])
            self.assertTrue(rec['craft_tags'])
            self.assertTrue(rec['prose_usefulness'])


if __name__ == '__main__':
    unittest.main()
