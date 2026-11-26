"""
Ingest downloaded books into books/text/ and books/manifest.json.

Reads `books/incoming/*.txt` (and optionally .pdf), strips Gutenberg boilerplate,
writes a canonical text file, and upserts a manifest entry. Existing manifest
entries are preserved; `--force` overwrites the text file.

    python tools/book_ingest.py --incoming books/incoming --books books
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from book_sources.epub import extract_epub_text
from book_sources.gutenberg import strip_gutenberg_boilerplate


def clean_text(text: str) -> str:
    if "PROJECT GUTENBERG EBOOK" in text.upper():
        text = strip_gutenberg_boilerplate(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def estimate_pages(words: int) -> int:
    return max(1, round(words / 300))


def load_sidecar(incoming: Path) -> Dict[str, dict]:
    path = incoming / "_candidates.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {entry["slug"]: entry for entry in data.get("books", []) if "slug" in entry}


def read_book(path: Path) -> str:
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".pdf":
        import pymupdf

        document = pymupdf.open(path)
        return "\n\n".join(page.get_text("text") for page in document)
    if path.suffix.lower() == ".epub":
        return extract_epub_text(path)
    if path.suffix.lower() in {".mobi", ".lit"}:
        raise ValueError(
            f"{path.suffix} is a Kindle/Microsoft Reader e-book; convert a DRM-free copy "
            f"to EPUB or TXT first (Calibre: ebook-convert), then ingest it. DRM is not supported."
        )
    raise ValueError(f"unsupported book format: {path.suffix} ({path})")


def ingest_incoming(
    incoming: Path,
    books_dir: Path,
    force: bool = False,
    dry_run: bool = False,
) -> List[dict]:
    incoming = Path(incoming)
    books_dir = Path(books_dir)
    if not incoming.is_dir():
        raise SystemExit(f"incoming directory not found: {incoming}")

    sidecar = load_sidecar(incoming)
    manifest_path = books_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"books": [], "count": 0}
    by_slug = {entry["slug"]: entry for entry in manifest.get("books", [])}

    text_dir = books_dir / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    ingested: List[dict] = []

    for path in sorted(incoming.iterdir()):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in {".mobi", ".lit"}:
            print(f"skip ({suffix} needs EPUB/TXT conversion first): {path.name}")
            continue
        if suffix not in {".txt", ".pdf", ".epub"}:
            continue
        if path.name.startswith("_"):
            continue
        if path.name.lower().startswith("readme"):
            continue

        slug = path.stem
        meta = sidecar.get(slug, {})
        title = meta.get("title") or slug.replace("_", " ").title()
        author = meta.get("author", "")
        year = meta.get("year", "")
        source = meta.get("source") or f"local:{path}"

        raw = read_book(path)
        from prose_engine.scoped_references import sanitize_reference_excerpt
        text = sanitize_reference_excerpt(clean_text(raw))
        if len(text.split()) < 500:
            print(f"skip (too short): {path.name} ({len(text.split())} words)")
            continue

        target = text_dir / f"{slug}.txt"
        if target.exists() and not force:
            print(f"skip (exists; use --force): {target.relative_to(books_dir)}")
        elif not dry_run:
            target.write_text(text, encoding="utf-8")

        words = len(text.split())
        entry = {
            "slug": slug,
            "id": slug,
            "title": title,
            "author": author,
            "year": str(year),
            "source": source,
            "pages": estimate_pages(words),
            "characters": len(text),
            "words": words,
            "file": f"text/{slug}.txt",
            "text_path": f"books/text/{slug}.txt",
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }
        by_slug[slug] = entry
        ingested.append(entry)

    if not dry_run:
        manifest["books"] = sorted(by_slug.values(), key=lambda item: item["slug"])
        manifest["count"] = len(manifest["books"])
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        from prose_engine.scoped_references import sync_obscured_titles
        sync_obscured_titles(books_dir, manifest["books"])
    return ingested


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest downloaded books into the corpus")
    parser.add_argument("--incoming", default=str(ROOT / "books" / "incoming"))
    parser.add_argument("--books", default=str(ROOT / "books"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    entries = ingest_incoming(
        Path(args.incoming), Path(args.books), force=args.force, dry_run=args.dry_run
    )
    for entry in entries:
        print(f"{entry['slug']:<60} {entry['words']:>9,} words  {entry['title'][:40]}")
    print(f"\n{len(entries)} book(s) ingested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
