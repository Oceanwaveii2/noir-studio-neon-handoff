"""
Extract the corrections PDF into labeled spans.

Red   = the author's "bad AI writing" marks (positive examples for a slop detector)
Green = scene direction notes
Black = the text as it stood

    python tools/extract_corrections.py --pdf "C:\\NOIR_LOCAL\\Downloads\\Corrections II.pdf"

Writes books/corrections.jsonl and prints a summary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf


def classify_color(color: int) -> str:
    r, g, b = (color >> 16) & 255, (color >> 8) & 255, color & 255
    if r > 120 and g < 90 and b < 90:
        return "bad"
    if g > 90 and r < 100 and b < 90:
        return "note"
    return "neutral"


def extract(path: str | Path):
    doc = pymupdf.open(str(path))
    rows = []
    for page_number, page in enumerate(doc, 1):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [span for span in line["spans"] if span["text"].strip()]
                if not spans:
                    continue
                text = "".join(span["text"] for span in spans).strip()
                if not text:
                    continue
                total = sum(len(span["text"]) for span in spans)
                counts = {"bad": 0, "note": 0, "neutral": 0}
                for span in spans:
                    counts[classify_color(span["color"])] += len(span["text"])
                label = max(counts, key=counts.get)
                if counts[label] / total < 0.5:
                    label = "neutral"
                rows.append(
                    {
                        "doc_id": Path(path).stem,
                        "page": page_number,
                        "label": label,
                        "op": "delete" if label == "bad" else ("keep" if label == "neutral" else "note"),
                        "text": text,
                    }
                )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--out", default="books/corrections.jsonl")
    args = parser.parse_args()

    rows = extract(args.pdf)
    v2 = Path(args.out).with_name(Path(args.out).stem + "_v2.jsonl")
    with v2.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"written v2 (span op + doc_id): {v2}")
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    counts = {"bad": 0, "note": 0, "neutral": 0}
    for row in rows:
        counts[row["label"]] += 1
    print(f"lines: {len(rows)} | {counts}")
    print(f"written: {target}")
    print("\n=== bad samples ===")
    for row in [row for row in rows if row["label"] == "bad"][:12]:
        print(" -", row["text"][:110])
    print("\n=== note samples ===")
    for row in [row for row in rows if row["label"] == "note"][:8]:
        print(" -", row["text"][:110])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
