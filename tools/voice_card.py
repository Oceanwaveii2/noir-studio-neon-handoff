"""
Voice card: the corpus's measurable habits, written as instructions for the prompt.

    python tools/voice_card.py --books books
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.styleprint import CONTRACTIONS, SENTENCE, _words  # noqa: E402

OPENERS = re.compile(r"(?:^|[.!?]\s+)([A-Z][a-z]+)")


def build(books: str | Path) -> Path:
    root = Path(books)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    texts = []
    for entry in manifest.get("books", []):
        if int(entry.get("words") or 0) <= 0:
            continue
        path = root / entry.get("file", f"text/{entry['slug']}.txt")
        if path.is_file():
            texts.append(path.read_text(encoding="utf-8"))
    if not texts:
        raise SystemExit("no corpus text found")

    sentences = [s.strip() for text in texts for s in SENTENCE.findall(text) if len(s.strip()) > 1]
    lengths = [len(_words(s)) for s in sentences]
    words = sum(len(_words(text)) for text in texts)
    mean = sum(lengths) / len(lengths)
    short = sum(1 for length in lengths if length < 7) / len(lengths) * 100
    long = sum(1 for length in lengths if length > 25) / len(lengths) * 100
    contractions = sum(len(CONTRACTIONS.findall(text)) for text in texts) / words * 1000
    chars = sum(len(text) for text in texts)

    quoted = 0
    for text in texts:
        quoted += sum(len(match.split()) for match in re.findall(r"[“\"]([^”\"]+)[”\"]", text))
    dialogue = quoted / words * 100

    marks = {"comma": ",", "em-dash": "—", "ellipsis": "…", "semicolon": ";"}
    per_k = {name: sum(text.count(mark) for text in texts) / chars * 1000 for name, mark in marks.items()}

    openers = Counter()
    for text in texts[:3]:
        for match in OPENERS.findall(text):
            openers[match] += 1
    top_openers = [word for word, _count in openers.most_common(8)]

    card = f"""HOUSE VOICE (measured from {len(texts)} reference books, {words:,} words)
- sentence length: mean {mean:.1f} words; {short:.0f}% are under 7 words; {long:.0f}% over 25
- dialogue: {dialogue:.0f}% of the words sit inside quotation marks
- punctuation per 1,000 characters: {per_k['comma']:.0f} commas, {per_k['em-dash']:.2f} em-dashes, {per_k['ellipsis']:.2f} ellipses, {per_k['semicolon']:.2f} semicolons
- contractions: {contractions:.0f} per 1,000 words
- frequent sentence openers: {", ".join(top_openers)}

Match this profile. Actively borrow the phrasing, cadence, and idioms of the reference passages to condition the prose.
"""
    target = root / "voice_card.md"
    target.write_text(card, encoding="utf-8")
    return target


def load(books: str | Path = "books") -> str:
    path = Path(books) / "voice_card.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--books", default="books")
    args = parser.parse_args()
    target = build(args.books)
    print(target.read_text(encoding="utf-8"))
    print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
