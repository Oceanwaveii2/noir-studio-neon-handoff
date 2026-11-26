"""
Book corpus for the standalone prose engine.

Loads the reference books extracted from PDF (books/manifest.json + books/text/*.txt),
measures them with the same diagnostics the engine uses at rewrite time, derives a style
profile from the measured cadence and sensory vocabulary, and selects reference passages to
put in front of the model.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .diagnostics import ProseDiagnosticsAnalyzer
from .semantic_drive import ReferencePassage
from .style_engine import STANDARD_DRAMATIC, StyleProfile

_QUOTED = re.compile(r"[\"\u201c]([^\"\u201d]{1,400})[\"\u201d]")


@dataclass
class Book:
    slug: str
    title: str
    author: str
    text: str
    pages: int = 0
    path: Optional[Path] = None


def load_corpus(books_dir: str | Path = "books") -> List[Book]:
    """Loads usable books; retained quality-quarantined records are not craft sources."""
    from .library_indexes import quality_exclusions
    root = Path(books_dir)
    excluded = quality_exclusions(root)
    books: List[Book] = []
    manifest = root / "manifest.json"

    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for entry in data.get("books", []):
            if entry["slug"] in excluded:
                continue
            text_path = root / entry.get("file", f"text/{entry['slug']}.txt")
            if not text_path.is_file():
                continue
            text = text_path.read_text(encoding="utf-8")
            if not text.strip():
                continue
            books.append(
                Book(
                    slug=entry["slug"],
                    title=entry.get("title") or entry["slug"],
                    author=entry.get("author", ""),
                    text=text,
                    pages=int(entry.get("pages", 0)),
                    path=text_path,
                )
            )
        return books

    for text_path in sorted((root / "text").glob("*.txt")):
        if text_path.stem in excluded:
            continue
        text = text_path.read_text(encoding="utf-8")
        if text.strip():
            books.append(
                Book(slug=text_path.stem, title=text_path.stem, author="", text=text, path=text_path)
            )
    return books


def _dialogue_word_ratio(text: str) -> float:
    quoted_words = sum(len(match.split()) for match in _QUOTED.findall(text))
    words = len(text.split())
    return round(quoted_words / words, 4) if words else 0.0


def _paragraph_cadence(text: str, max_samples: int = 200) -> float:
    """Mean burstiness over sampled paragraphs — the scale the engine actually rewrites on."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        return 0.0
    step = max(1, len(paragraphs) // max_samples)
    values = []
    for paragraph in paragraphs[::step]:
        if len(paragraph.split()) < 30:
            continue
        report = ProseDiagnosticsAnalyzer.analyze(paragraph)
        if report.burstiness_score > 0:
            values.append(report.burstiness_score)
    return round(sum(values) / len(values), 2) if values else 0.0


def book_stats(book: Book) -> Dict:
    """Measures one book: cadence, sensory density, filter words, dialogue ratio."""
    report = ProseDiagnosticsAnalyzer.analyze(book.text)
    sentences = ProseDiagnosticsAnalyzer.split_into_sentences(book.text)
    words = len(book.text.split())
    return {
        "slug": book.slug,
        "title": book.title,
        "author": book.author,
        "pages": book.pages,
        "words": words,
        "sentences": len(sentences),
        "mean_sentence_length": round(report.average_sentence_length, 2),
        "burstiness": round(report.burstiness_score, 2),
        "paragraph_burstiness": _paragraph_cadence(book.text),
        "sensory_details": report.sensory_details_count,
        "sensory_per_1k_words": round(report.sensory_details_count * 1000 / words, 2) if words else 0.0,
        "filter_words": report.filter_word_count,
        "emotion_labels": len(report.label_examples),
        "dialogue_ratio": _dialogue_word_ratio(book.text),
    }


def corpus_index(books: List[Book]) -> Dict:
    """Per-book stats plus corpus aggregates."""
    per_book = [book_stats(book) for book in books]
    total_words = sum(entry["words"] for entry in per_book) or 1
    aggregate = {
        "books": len(per_book),
        "words": sum(entry["words"] for entry in per_book),
        "sentences": sum(entry["sentences"] for entry in per_book),
        "mean_sentence_length": round(
            sum(entry["mean_sentence_length"] * entry["words"] for entry in per_book) / total_words, 2
        ),
        "burstiness": round(
            sum(entry["paragraph_burstiness"] * entry["words"] for entry in per_book) / total_words, 2
        ),
        "whole_book_burstiness": round(
            sum(entry["burstiness"] * entry["words"] for entry in per_book) / total_words, 2
        ),
        "sensory_per_1k_words": round(
            sum(entry["sensory_details"] for entry in per_book) * 1000 / total_words, 2
        ),
        "dialogue_ratio": round(
            sum(entry["dialogue_ratio"] * entry["words"] for entry in per_book) / total_words, 4
        ),
        "filter_words": sum(entry["filter_words"] for entry in per_book),
        "emotion_labels": sum(entry["emotion_labels"] for entry in per_book),
    }
    return {"aggregate": aggregate, "books": per_book}


def _top_sensory_terms(books: List[Book], limit: int = 12) -> List[str]:
    counts: Dict[str, int] = {}
    for book in books:
        lowered = book.text.lower()
        for lexicon in ProseDiagnosticsAnalyzer.SENSORY_LEXICON.values():
            for term in lexicon:
                if term in lowered:
                    counts[term] = counts.get(term, 0) + lowered.count(term)
    return [term for term, _count in sorted(counts.items(), key=lambda item: -item[1])[:limit]]


def derive_style_profile(
    books: List[Book],
    profile_id: str = "corpus",
    name: str = "House Corpus",
    base: Optional[StyleProfile] = None,
) -> StyleProfile:
    """Builds a style profile from measurements of the corpus (cadence and sensory vocabulary)."""
    if not books:
        raise ValueError("Cannot derive a style profile from an empty corpus")
    base = base or STANDARD_DRAMATIC
    index = corpus_index(books)
    aggregate = index["aggregate"]
    sensory = _top_sensory_terms(books)
    measured_cadence = aggregate["burstiness"]
    # Literary paragraphs vary widely (10-24); using that as a *target* pushes choppy prose.
    # Keep the measured value in the description, but aim rewrites at a human range.
    target_cadence = round(max(3.5, min(8.0, measured_cadence)), 2)

    return base.model_copy(
        update={
            "profile_id": profile_id,
            "name": name,
            "description": (
                f"Derived from {len(books)} reference books "
                f"({aggregate['words']:,} words; measured paragraph cadence {measured_cadence:.2f}, "
                f"{aggregate['sensory_per_1k_words']:.2f} sensory anchors per 1k words)."
            ),
            "target_cadence_burstiness": target_cadence,
            "voice_principles": list(base.voice_principles)
            + [
                f"Corpus measured paragraph cadence {measured_cadence:.2f}; keep rewrites at or "
                f"above {target_cadence:.2f} (sentence-length variation).",
                f"Corpus dialogue density: {aggregate['dialogue_ratio']:.1%} of words are spoken.",
                "Hold at least one concrete sensory anchor per paragraph.",
            ],
            "sensory_preferences": sensory,
        }
    )


def reference_passages(
    books: List[Book],
    profile_id: str = "corpus",
    count: int = 8,
    min_words: int = 40,
    max_words: int = 120,
) -> List[ReferencePassage]:
    """Selects the best-scoring passages across the corpus (sensory density minus filters)."""
    scored: List[tuple[float, ReferencePassage]] = []
    for book in books:
        sentences = ProseDiagnosticsAnalyzer.split_into_sentences(book.text)
        if len(sentences) < 2:
            continue
        step = max(1, len(sentences) // 120)
        for start in range(0, len(sentences) - 1, step):
            window: List[str] = []
            words = 0
            for sentence in sentences[start : start + 6]:
                window.append(sentence)
                words += len(sentence.split())
                if words >= min_words:
                    break
            if words < min_words or words > max_words:
                continue
            text = " ".join(window)
            report = ProseDiagnosticsAnalyzer.analyze(text)
            score = (
                report.sensory_details_count * 2.0
                + min(report.burstiness_score, 8.0)
                - report.filter_word_count * 2.0
                - len(report.label_examples)
            )
            scored.append(
                (
                    score,
                    ReferencePassage(
                        passage_id=f"{book.slug}-{start}",
                        profile_id=profile_id,
                        text=text,
                        scene_type="corpus",
                        tags=[book.slug],
                    ),
                )
            )
    scored.sort(key=lambda item: -item[0])
    return [passage for _score, passage in scored[:count]]


def save_passages(passages: List[ReferencePassage], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps([passage.model_dump() for passage in passages], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return target


def load_passages(path: str | Path) -> List[ReferencePassage]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [ReferencePassage(**entry) for entry in data]
