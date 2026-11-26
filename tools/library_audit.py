"""Read-only source/text/PDF reconciliation. Flags require review, not deletion."""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prose_engine.library_indexes import catalog, digest, safe_child


def audit(root):
    import pymupdf
    entries = json.loads((root / "manifest.json").read_text(encoding="utf-8"))["books"]
    before = catalog(root)
    records, duplicates, files = [], defaultdict(list), set()
    for entry in entries:
        path = safe_child(root, entry.get("file", f"text/{entry['slug']}.txt"))
        files.add(path.absolute())
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        words = len(text.split())
        flags = []
        if not text.strip(): flags.append("blank-or-missing: excluded from indexes")
        if 0 < words < 1500: flags.append("short text/excerpt, not evidence of a complete book")
        bad = text.count("\ufffd")
        if bad: flags.append("replacement characters: inspect extraction")
        if entry.get("words") != words: flags.append("manifest word count differs from current text")
        normalized = re.sub(r"\s+", " ", text).strip()
        if normalized: duplicates[hashlib.sha256(normalized.encode()).hexdigest()].append(entry["slug"])
        source_record = entry.get("source", "")
        source = safe_child(root.parent, source_record[6:]) if source_record.startswith("local:") else Path(source_record)
        record = {"source_id": entry["slug"], "title": entry.get("title"), "author": entry.get("author"),
                  "text_file": str(path.relative_to(root)), "text_sha256": digest(path) if path.is_file() else "missing",
                  "words": words, "characters": len(text), "replacement_characters": bad,
                  "source_record": entry.get("source"), "source_available": source.is_file(), "flags": flags}
        embedded = re.search(r"^Title:\s*(.+)", text[:5000], re.M)
        if embedded: record["embedded_title"] = embedded.group(1).strip()
        if source.is_file():
            record["source_sha256"] = digest(source)
        if source.is_file() and source.suffix.lower() == ".pdf":
            low, image_only, page_words = [], [], []
            try:
                with pymupdf.open(source) as pdf:
                    for number, page in enumerate(pdf, 1):
                        count = len(page.get_text().split()); page_words.append(count)
                        if count < 10:
                            low.append(number)
                            if page.get_images(): image_only.append(number)
                    record["pdf"] = {"pages": len(pdf), "extracted_words": sum(page_words),
                                     "pages_under_10_words": low, "low_text_pages_with_images": image_only,
                                     "ocr_review": "Image-bearing low-text pages need visual/OCR review; illustrations and covers may be intentional." if image_only else "No image-bearing low-text pages detected; not an OCR accuracy guarantee."}
                    if image_only: flags.append("possible image-only text; OCR not adjudicated")
            except Exception as exc:
                record["pdf"] = {"error": str(exc)}; flags.append("PDF not reliably readable")
        elif not source.is_file():
            flags.append("original source unavailable or bibliographic-only; text completeness unverified")
        records.append(record)
    if catalog(root) != before: raise ValueError("Library changed during audit")
    return {"schema_version": 1, "catalog": before["fingerprint"], "manifest_entries": len(entries),
            "usable_nonblank_texts": sum(r["words"] > 0 for r in records),
            "source_files_available": sum(r["source_available"] for r in records),
            "pdfs_checked_all_pages": sum("pdf" in r for r in records),
            "unmanifested_text_files": [str(p.relative_to(root)) for p in (root / "text").glob("*.txt") if p.absolute() not in files],
            "exact_normalized_duplicate_groups": [v for v in duplicates.values() if len(v) > 1], "sources": records,
            "limitations": ["No source or text modified, no OCR/model call performed.",
                            "Nonblank readable text can still be an excerpt, anthology, mislabelled or poorly OCRed; flags are not literary acceptance.",
                            "Separate editions and duplicate records retained. Missing originals cannot be retrospectively verified."]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--books", type=Path, default=Path("books")); p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    report = audit(args.books.absolute())
    with args.out.open("x", encoding="utf-8") as stream: json.dump(report, stream, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k not in {"sources"}}))


if __name__ == "__main__": main()
