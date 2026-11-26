"""
Extract plain text from the reference-book PDFs into the corpus.

    python tools/extract_books.py --pdf-dir "D:\\...\\01_Test_PDFs" --out books

Writes books/text/<slug>.txt and books/manifest.json. Extraction is deterministic for a
given PyMuPDF version; the manifest records pages, characters, and words per book.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

import pymupdf

# Title and author for each source file (from the file names; left blank when unknown).
META: Dict[str, Tuple[str, str]] = {
    "Pulp-fiction-quentin-tarantino.pdf": ("Pulp Fiction", "Quentin Tarantino"),
    "sample-miami-by-giordano-poloni.pdf": ("Miami (sample)", "Giordano Poloni"),
    "sample-shihatsu-densha-by-robert-herzig.pdf": ("Shihatsu Densha (sample)", "Robert Herzig"),
    "sample-vision-by-nastka-drabot.pdf": ("Vision (sample)", "Nastka Drabot"),
    "Star_-_Pamela_Anderson.pdf": ("Star", "Pamela Anderson"),
    "The_Love_Machine_-_Jacqueline_Susann.pdf": ("The Love Machine", "Jacqueline Susann"),
    "The_World_is_Full_of_Divorced_Women_-_Jackie_Collins.pdf": (
        "The World Is Full of Divorced Women",
        "Jackie Collins",
    ),
    "Valley_of_the_Dolls_-_Jacqueline_Susann.pdf": ("Valley of the Dolls", "Jacqueline Susann"),
    "We-are-never-meeting-in-real-life-essays.pdf": ("We Are Never Meeting in Real Life", ""),
    "01 - Fool.pdf": ("Fool", ""),
    "gentlemenpreferb0000anit.pdf": ("Gentlemen Prefer Blondes", "Anita Loos"),
    "Luster_-_Raven_Leilani.pdf": ("Luster", "Raven Leilani"),
    "No_One_Is_Talking_About_This_-_Patricia_Lockwood.pdf": (
        "No One Is Talking About This",
        "Patricia Lockwood",
    ),
}

_SENTENCE_END = re.compile(r"[.!?\"'\u201d\u2019)\]]$")
_PAGE_NUMBER = re.compile(r"^\s*(?:page\s*)?\d{1,4}\s*$", re.IGNORECASE)


def slugify(name: str) -> str:
    stem = re.sub(r"\.pdf$", "", name, flags=re.IGNORECASE)
    slug = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")
    return slug or "book"


def _repeated_lines(pages: List[str], minimum_ratio: float = 0.3) -> set:
    """Running headers/footers repeat on most pages; drop them."""
    if len(pages) < 10:
        return set()
    counts: Dict[str, int] = {}
    for page in pages:
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        if not lines:
            continue
        for candidate in {lines[0], lines[-1]}:
            if 2 <= len(candidate) <= 80:
                counts[candidate] = counts.get(candidate, 0) + 1
    threshold = max(3, int(len(pages) * minimum_ratio))
    return {line for line, count in counts.items() if count >= threshold}


def clean_pages(pages: List[str]) -> str:
    repeated = _repeated_lines(pages)
    paragraphs: List[str] = []
    for page in pages:
        lines = []
        for line in page.splitlines():
            stripped = line.strip()
            if not stripped or _PAGE_NUMBER.match(stripped) or stripped in repeated:
                continue
            lines.append(stripped)
        if not lines:
            continue

        text = " ".join(lines)
        # Re-join words hyphenated across a line break: "condi- tioned" -> "conditioned".
        text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
        text = re.sub(r"[ \t]{2,}", " ", text).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def extract_one(pdf: Path, out_dir: Path) -> dict:
    document = pymupdf.open(pdf)
    pages = [page.get_text("text") for page in document]
    text = clean_pages(pages)
    slug = slugify(pdf.name)
    (out_dir / "text").mkdir(parents=True, exist_ok=True)
    (out_dir / "text" / f"{slug}.txt").write_text(text + "\n", encoding="utf-8")

    title, author = META.get(pdf.name, (pdf.stem.replace("_", " "), ""))
    return {
        "slug": slug,
        "title": title,
        "author": author,
        "source": str(pdf),
        "pages": len(pages),
        "characters": len(text),
        "words": len(text.split()),
        "file": f"text/{slug}.txt",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract reference books from PDF")
    parser.add_argument("--pdf-dir", required=True)
    parser.add_argument("--out", default="books")
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    books = []
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        entry = extract_one(pdf, out_dir)
        books.append(entry)
        print(f"{entry['slug']:<55} {entry['pages']:>4} pages {entry['words']:>8,} words")

    manifest = {"books": books, "count": len(books)}
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n{len(books)} books -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
