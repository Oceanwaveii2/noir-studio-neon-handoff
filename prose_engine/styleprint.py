"""
Stylometric fingerprint: a measurable voice, independent of topic.

Semantic cosine says "about the same thing". This says "sounds like the same writer": function
words, punctuation habits, sentence-length distribution, dialogue share, contraction rate.

    python styleprint.py build --books books
    python styleprint.py show --file draft.md --books books
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np

FUNCTION_WORDS = [
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "at", "for", "with",
    "from", "by", "as", "that", "this", "these", "those", "it", "its", "she", "he", "her",
    "his", "him", "they", "them", "their", "we", "you", "i", "not", "no", "was", "were",
    "is", "are", "had", "have", "has", "did", "do", "does", "would", "could", "should",
    "just", "like", "so", "then", "when", "what", "who", "how", "there", "here", "up",
    "down", "out", "into", "over", "after", "before", "because", "while", "about",
]

PUNCT = {
    "comma": ",", "period": ".", "question": "?", "exclaim": "!",
    "semicolon": ";", "colon": ":", "dash": "—", "ellipsis": "…",
}

CONTRACTIONS = re.compile(r"\b\w+(?:'|’)(?:s|t|ll|re|ve|d|m)\b|\b\w+n't\b", re.IGNORECASE)
SENTENCE = re.compile(r"[^.!?]+[.!?]+")
QUOTED = re.compile(r"[“\"]([^”\"]+)[”\"]")


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text.lower())


def fingerprint(text: str) -> np.ndarray:
    words = _words(text)
    total = max(1, len(words))
    counts = Counter(words)
    values: list[float] = []
    for word in FUNCTION_WORDS:
        values.append(counts.get(word, 0) / total * 1000)
    length = max(1, len(text))
    for mark in PUNCT.values():
        values.append(text.count(mark) / length * 1000)
    sentences = [segment.strip() for segment in SENTENCE.findall(text) if segment.strip()]
    lengths = [len(_words(segment)) for segment in sentences] or [0]
    mean = float(np.mean(lengths))
    sd = float(np.std(lengths))
    values.extend(
        [
            mean,
            sd,
            sum(1 for length_ in lengths if length_ < 7) / len(lengths) * 100,
            sum(1 for length_ in lengths if length_ > 25) / len(lengths) * 100,
            sum(len(match.split()) for match in QUOTED.findall(text)) / total * 100,
            len(CONTRACTIONS.findall(text)) / total * 1000,
        ]
    )
    return np.array(values, dtype=float)


NAMES = (
    [f"fw:{word}" for word in FUNCTION_WORDS]
    + [f"punct:{name}" for name in PUNCT]
    + ["sent:mean", "sent:sd", "sent:short_pct", "sent:long_pct", "dialogue_word_pct", "contractions_per_k"]
)


def load_corpus_texts(books: str | Path) -> list[tuple[str, str]]:
    root = Path(books)
    manifest = root / "manifest.json"
    items: list[tuple[str, str]] = []
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for entry in data.get("books", []):
            if int(entry.get("words") or 0) <= 0:
                continue
            path = root / entry.get("file", f"text/{entry['slug']}.txt")
            if path.is_file():
                items.append((entry["slug"], path.read_text(encoding="utf-8")))
    else:
        for path in sorted((root / "text").glob("*.txt")):
            items.append((path.stem, path.read_text(encoding="utf-8")))
    return items


def build(books: str | Path) -> dict:
    items = load_corpus_texts(books)
    if not items:
        raise SystemExit("no corpus text found")
    vectors = np.array([fingerprint(text) for _slug, text in items])
    model = {
        "names": NAMES,
        "books": [slug for slug, _text in items],
        "mean": vectors.mean(axis=0).round(4).tolist(),
        "sd": np.maximum(vectors.std(axis=0), 1e-6).round(4).tolist(),
        "per_book": {
            slug: vectors[index].round(4).tolist() for index, (slug, _text) in enumerate(items)
        },
    }
    target = Path(books) / "styleprint.json"
    target.write_text(json.dumps(model, indent=2), encoding="utf-8")
    print(f"styleprint: {len(items)} books, {len(NAMES)} features -> {target}")
    return model


def distance(vector: np.ndarray, model: dict) -> float:
    mean = np.array(model["mean"], dtype=float)
    sd = np.array(model["sd"], dtype=float)
    z = np.clip((vector - mean) / sd, -3.0, 3.0)  # cap outliers: short paragraphs are noisy
    return float(np.sqrt(np.mean(z * z)))


def distance_between(query: np.ndarray, reference: np.ndarray, model: dict) -> float:
    sd = np.array(model["sd"], dtype=float)
    return float(np.sqrt(np.mean(((query - reference) / sd) ** 2)))


def nearest_book(vector: np.ndarray, model: dict) -> tuple[str, float]:
    ranked = sorted(
        (
            (slug, distance_between(vector, np.array(values, dtype=float), model))
            for slug, values in model["per_book"].items()
        ),
        key=lambda pair: pair[1],
    )
    return ranked[0] if ranked else ("", 0.0)


def load_model(books: str | Path) -> dict | None:
    path = Path(books) / "styleprint.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(prog="styleprint")
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--books", default="books")
    show_parser = sub.add_parser("show")
    show_parser.add_argument("--file", required=True)
    show_parser.add_argument("--books", default="books")
    args = parser.parse_args()

    if args.command == "build":
        build(args.books)
        return 0

    model = load_model(args.books)
    if model is None:
        raise SystemExit("no styleprint; run: python styleprint.py build --books books")
    text = Path(args.file).read_text(encoding="utf-8")
    vector = fingerprint(text)
    book, book_distance = nearest_book(vector, model)
    print(f"style distance to corpus: {distance(vector, model):.3f} (lower is closer)")
    print(f"nearest book: {book} ({book_distance:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
