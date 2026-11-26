"""
Offline tests for the book-expansion tooling: source registry, boilerplate stripping,
curated spring ranking, ingest into the manifest, and index dry-run.
"""

from __future__ import annotations

import json
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from book_ingest import ingest_incoming
from book_sources import SPRING_BATCH, default_sources
from book_sources.epub import extract_epub_text
from book_sources.gutenberg import strip_gutenberg_boilerplate
from book_tools import CATALOGS, TOOLS, inventory
from index_books import run_index


SAMPLE = (
    "The party was loud and the room smelled of perfume and cigarettes. "
    "She wore a crimson dress and laughed at the wrong moment. "
) * 40


def make_epub(path: Path, chapters: list[str]) -> None:
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title><dc:identifier id="id">test</dc:identifier>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    {items}
  </manifest>
  <spine>{spine}</spine>
</package>
"""
    items = []
    spine = []
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        for index, chapter in enumerate(chapters, start=1):
            name = f"ch{index}.xhtml"
            items.append(
                f'<item id="ch{index}" href="{name}" media-type="application/xhtml+xml"/>'
            )
            spine.append(f'<itemref idref="ch{index}"/>')
            zf.writestr(
                f"OEBPS/{name}",
                '<?xml version="1.0" encoding="utf-8"?>'
                '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head><body>'
                f"{chapter}</body></html>",
            )
        zf.writestr("OEBPS/nav.xhtml", "<html><body><nav>Navigation should be skipped</nav></body></html>")
        zf.writestr("OEBPS/content.opf", opf.format(items="\n".join(items), spine="".join(spine)))


class TestBookExpansion(unittest.TestCase):
    def test_strip_gutenberg_boilerplate(self):
        raw = (
            "The Project Gutenberg eBook of Test\n\n"
            "*** START OF THE PROJECT GUTENBERG EBOOK TEST ***\n\n"
            "Chapter One\n\nIt was a bright cold day.\n\n"
            "*** END OF THE PROJECT GUTENBERG EBOOK TEST ***\n"
        )
        cleaned = strip_gutenberg_boilerplate(raw)
        self.assertIn("It was a bright cold day.", cleaned)
        self.assertNotIn("START OF THE PROJECT GUTENBERG", cleaned)
        self.assertNotIn("END OF THE PROJECT GUTENBERG", cleaned)

    def test_curated_spring_batch(self):
        ids = {book.gutenberg_id for book in SPRING_BATCH}
        self.assertGreaterEqual(len(SPRING_BATCH), 10)
        self.assertIn("11052", ids)  # The Custom of the Country
        self.assertIn("3472", ids)  # Merton of the Movies
        self.assertTrue(all(book.themes for book in SPRING_BATCH))

    def test_default_sources(self):
        ids = {source.id for source in default_sources()}
        for required in (
            "gutenberg",
            "openlibrary",
            "internet_archive",
            "google_books",
            "doab",
            "oapen",
            "openstax",
            "nap",
            "local",
            "external_url",
        ):
            self.assertIn(required, ids)

    def test_book_tool_inventory(self):
        data = inventory()
        self.assertEqual(len(data["tools"]), 5)
        self.assertEqual(len(data["catalogs"]), 15)
        shadow = [c for c in CATALOGS if "NOT_AUTOMATED" in c["status"]]
        self.assertGreaterEqual(len(shadow), 6)

    def test_ingest_updates_manifest(self):
        incoming = self._tmp / "incoming"
        books = self._tmp / "books"
        incoming.mkdir(parents=True)
        books.mkdir(parents=True)
        (incoming / "sample_book.txt").write_text(SAMPLE, encoding="utf-8")
        (incoming / "_candidates.json").write_text(
            json.dumps(
                {
                    "books": [
                        {
                            "slug": "sample_book",
                            "title": "Sample Book",
                            "author": "Test Author",
                            "year": "1922",
                            "source": "https://example.test/book",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        entries = ingest_incoming(incoming, books)
        self.assertEqual(len(entries), 1)
        self.assertTrue((books / "text" / "sample_book.txt").is_file())
        manifest = json.loads((books / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["count"], 1)
        self.assertEqual(manifest["books"][0]["title"], "Sample Book")
        self.assertEqual(manifest["books"][0]["author"], "Test Author")

    def test_extract_epub_text(self):
        path = self._tmp / "book.epub"
        make_epub(
            path,
            [
                "<h1>Chapter One</h1><p>It was a bright cold day in April.</p>"
                "<p>She wore a crimson dress &amp; laughed.</p>",
                "<h1>Chapter Two</h1><p>The party was loud.</p>",
            ],
        )
        text = extract_epub_text(path)
        self.assertIn("Chapter One", text)
        self.assertIn("Chapter Two", text)
        self.assertIn("crimson dress & laughed", text)
        self.assertNotIn("Navigation should be skipped", text)
        self.assertNotIn("<p>", text)
        self.assertLess(text.index("Chapter One"), text.index("Chapter Two"))

    def test_ingest_epub(self):
        incoming = self._tmp / "incoming"
        books = self._tmp / "books"
        incoming.mkdir(parents=True)
        books.mkdir(parents=True)
        chapter = "<h1>Chapter</h1><p>" + SAMPLE.replace("\n", " ") + "</p>"
        make_epub(incoming / "epub_book.epub", [chapter, chapter])
        (incoming / "_candidates.json").write_text(
            json.dumps(
                {
                    "books": [
                        {
                            "slug": "epub_book",
                            "title": "EPUB Book",
                            "author": "Test Author",
                            "year": "2020",
                            "source": "local:epub",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        entries = ingest_incoming(incoming, books)
        self.assertEqual(len(entries), 1)
        self.assertTrue((books / "text" / "epub_book.txt").is_file())
        manifest = json.loads((books / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["books"][0]["title"], "EPUB Book")
        self.assertGreater(manifest["books"][0]["words"], 500)

    def test_index_full_dry_run(self):
        books = self._tmp / "books"
        books.mkdir(parents=True)
        (books / "manifest.json").write_text(
            json.dumps(
                {
                    "books": [
                        {
                            "slug": "sample_book",
                            "title": "Sample Book",
                            "author": "Test Author",
                            "words": len(SAMPLE.split()),
                            "file": "text/sample_book.txt",
                        }
                    ],
                    "count": 1,
                }
            ),
            encoding="utf-8",
        )
        (books / "text").mkdir()
        (books / "text" / "sample_book.txt").write_text(SAMPLE, encoding="utf-8")
        code = run_index(
            books_dir=books,
            index_path=books / "vector_index.joblib",
            mode="full",
            dry_run=True,
            backup=False,
        )
        self.assertEqual(code, 0)
        self.assertFalse((books / "vector_index.joblib").exists())

    def setUp(self):
        import tempfile

        self._tmp_dir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmp_dir.name)

    def tearDown(self):
        self._tmp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
