"""
Numeric style card: the books' measured habits, with no sentences to copy.

    python tools/build_style_card.py

Produces books/style_card.json and a prompt block such as:

    STYLE CARD (match these numbers; do not quote any source):
    - average sentence 11.4 words (sd 7.2); 44% of sentences are 8 words or shorter
    - similes 3.1 per 1000 words; participial tails 6.0 per 1000
    ...

This replaces passage references as the voice signal: the model cannot lift text from numbers.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List

from ..styleprint import load_corpus_texts

SENTENCE = re.compile(r"[^.!?]+[.!?]+")
WORD = re.compile(r"[A-Za-z']+")
SIMILE = re.compile(r"\b(?:like a|like an|like the|as if|as though)\b", re.IGNORECASE)
PARTICIPIAL = re.compile(r",\s+[a-z]+ing\b")
DIALOGUE = re.compile(r"^\s*(?:[-—\"“])")


@dataclass
class StyleCard:
    sentences: int
    mean_sentence: float
    sd_sentence: float
    short_share: float
    simile_per_1000: float
    participial_per_1000: float
    adverb_per_1000: float
    comma_per_100: float
    dash_per_100: float
    dialogue_share: float
    mean_paragraph: float

    def prompt_block(self) -> str:
        return "\n".join(
            [
                "STYLE CARD (match these measurements; do not quote or copy any source text):",
                f"- average sentence {self.mean_sentence:.1f} words (sd {self.sd_sentence:.1f}); "
                f"{self.short_share * 100:.0f}% of sentences are 8 words or shorter",
                f"- similes {self.simile_per_1000:.1f} per 1000 words; "
                f"participial tails {self.participial_per_1000:.1f} per 1000",
                f"- -ly adverbs {self.adverb_per_1000:.1f} per 1000; "
                f"commas {self.comma_per_100:.1f} per 100 words; dashes {self.dash_per_100:.1f} per 100",
                f"- dialogue lines {self.dialogue_share * 100:.0f}% of lines; "
                f"paragraphs average {self.mean_paragraph:.0f} words",
            ]
        )

    def save(self, path: str | Path = "books/style_card.json") -> Path:
        target = Path(path)
        target.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path | None = None) -> "StyleCard":
        from ..paths import books

        return cls(**json.loads(Path(path or books("style_card.json")).read_text(encoding="utf-8")))


def compute(books: str | Path = "books") -> StyleCard:
    items = load_corpus_texts(books)
    if not items:
        raise SystemExit("no corpus text found")
    sentences: List[int] = []
    words = similes = participials = adverbs = commas = dashes = lines = dialogue = 0
    paragraph_lengths: List[int] = []
    for _slug, text in items:
        for paragraph in [part for part in text.split("\n\n") if part.strip()]:
            paragraph_lengths.append(len(WORD.findall(paragraph)))
        for line in text.splitlines():
            if line.strip():
                lines += 1
                if DIALOGUE.match(line):
                    dialogue += 1
        for match in SENTENCE.finditer(text):
            length = len(WORD.findall(match.group(0)))
            if length:
                sentences.append(length)
        words += len(WORD.findall(text))
        similes += len(SIMILE.findall(text))
        participials += len(PARTICIPIAL.findall(text))
        adverbs += len(re.findall(r"\b\w+ly\b", text))
        commas += text.count(",")
        dashes += text.count("—")
    total = max(1, len(sentences))
    return StyleCard(
        sentences=len(sentences),
        mean_sentence=round(statistics.mean(sentences), 2),
        sd_sentence=round(statistics.pstdev(sentences), 2),
        short_share=round(sum(1 for length in sentences if length <= 8) / total, 3),
        simile_per_1000=round(similes / max(1, words) * 1000, 2),
        participial_per_1000=round(participials / max(1, words) * 1000, 2),
        adverb_per_1000=round(adverbs / max(1, words) * 1000, 2),
        comma_per_100=round(commas / max(1, words) * 100, 2),
        dash_per_100=round(dashes / max(1, words) * 100, 2),
        dialogue_share=round(dialogue / max(1, lines), 3),
        mean_paragraph=round(statistics.mean(paragraph_lengths), 1) if paragraph_lengths else 0.0,
    )
