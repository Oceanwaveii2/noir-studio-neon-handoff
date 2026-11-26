"""
Style guide: analyze writing samples and score candidates against the author's habits.

The method (from the "write like a human" transcript): give the model (a) real samples and
(b) a sentence-level analysis of those samples — narrative rhythm, sentence openings, clause
structure, punctuation habits, dialogue density, emphasis tricks. This module produces that
analysis deterministically and turns it into a similarity score the ranker can use.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence

from .diagnostics import ProseDiagnosticsAnalyzer as D

_SIMILE = re.compile(r"\b(?:like a|like an|as if|as though|like the)\b", re.IGNORECASE)
_OPENING = re.compile(r"(?:^|[.!?][\"'\u201d]?\s+)([A-Za-z']+)")


@dataclass
class StyleGuide:
    samples: int
    words: int
    sentences: int
    mean_sentence_length: float
    sentence_sd: float
    short_sentence_pct: float      # <= 5 words
    long_sentence_pct: float       # >= 25 words
    fragment_pct: float            # <= 3 words or no verb-ish token
    question_pct: float
    exclamation_per_1k: float
    emdash_per_1k: float
    semicolon_per_1k: float
    ellipsis_per_1k: float
    simile_per_1k: float
    sensory_per_1k: float
    top_openings: List[List] = field(default_factory=list)
    exemplars: Dict[str, str] = field(default_factory=dict)

    def to_markdown(self) -> str:
        openings = ", ".join(f"{word} ×{count}" for word, count in self.top_openings[:8])
        lines = [
            "# Style guide",
            "",
            f"Built from {self.samples} samples / {self.words:,} words / {self.sentences:,} sentences.",
            "",
            "## Narrative rhythm",
            f"- Mean sentence length {self.mean_sentence_length:.1f} words, variation {self.sentence_sd:.1f}.",
            f"- Short sentences (<=5 words): {self.short_sentence_pct:.1f}%.",
            f"- Long sentences (>=25 words): {self.long_sentence_pct:.1f}%.",
            f"- Fragments: {self.fragment_pct:.1f}%.",
            "",
            "## Sentence openings",
            f"- Most common first words: {openings or 'n/a'}.",
            "",
            "## Punctuation habits (per 1,000 words)",
            f"- Questions {self.question_pct:.1f}% · exclamation {self.exclamation_per_1k:.1f} · "
            f"em dash {self.emdash_per_1k:.1f} · semicolon {self.semicolon_per_1k:.1f} · "
            f"ellipsis {self.ellipsis_per_1k:.1f}.",
            "",
            "## Texture",
            f"- Similes {self.simile_per_1k:.1f}/1k · sensory anchors {self.sensory_per_1k:.1f}/1k.",
            "",
            "## Exemplars",
        ]
        for category, text in self.exemplars.items():
            lines.append(f"### {category}")
            lines.append(f"> {text[:280]}")
            lines.append("")
        return "\n".join(lines)


def _sentences(text: str) -> List[str]:
    return [s for s in D.split_into_sentences(text) if s.strip()]


def _has_verb(sentence: str) -> bool:
    return bool(
        re.search(
            r"\b(?:is|are|was|were|be|been|am|has|have|had|do|does|did|can|could|will|would|"
            r"shall|should|may|might|must|\w+ed|\w+s)\b",
            sentence.lower(),
        )
    )


def analyze_samples(samples: Sequence[str], exemplars: bool = True) -> StyleGuide:
    text = "\n\n".join(samples)
    sentences = _sentences(text)
    words = len(text.split()) or 1
    n = len(sentences) or 1
    lengths = [len(s.split()) for s in sentences]
    mean = sum(lengths) / n if lengths else 0.0
    sd = (sum((x - mean) ** 2 for x in lengths) / n) ** 0.5 if lengths else 0.0
    short = sum(1 for x in lengths if x <= 5) / n * 100
    long_ = sum(1 for x in lengths if x >= 25) / n * 100
    fragments = sum(1 for s in sentences if len(s.split()) <= 3 or not _has_verb(s)) / n * 100
    questions = sum(1 for s in sentences if s.rstrip().endswith("?")) / n * 100
    lowercase = text.lower()

    counts: Dict[str, int] = {}
    for match in _OPENING.finditer(text):
        word = match.group(1).lower()
        counts[word] = counts.get(word, 0) + 1
    openings = sorted(counts.items(), key=lambda item: -item[1])[:10]

    report = D.analyze(text)

    guide = StyleGuide(
        samples=len(samples),
        words=words,
        sentences=n,
        mean_sentence_length=round(mean, 2),
        sentence_sd=round(sd, 2),
        short_sentence_pct=round(short, 1),
        long_sentence_pct=round(long_, 1),
        fragment_pct=round(fragments, 1),
        question_pct=round(questions, 1),
        exclamation_per_1k=round(text.count("!") * 1000 / words, 1),
        emdash_per_1k=round(text.count("\u2014") * 1000 / words, 1),
        semicolon_per_1k=round(text.count(";") * 1000 / words, 1),
        ellipsis_per_1k=round(text.count("\u2026") * 1000 / words, 1),
        simile_per_1k=round(len(_SIMILE.findall(text)) * 1000 / words, 1),
        sensory_per_1k=round(report.sensory_details_count * 1000 / words, 1),
        top_openings=[[word, count] for word, count in openings],
    )

    if exemplars:
        ranked = sorted(
            sentences,
            key=lambda sentence: len(sentence.split()),
        )
        short_sample = " ".join(ranked[:3])
        long_sample = " ".join(ranked[-3:])
        dialogue = [s for s in sentences if s.count('"') or s.count("\u201c")]
        action = [s for s in sentences if len(s.split()) >= 8 and not _has_verb(s) is False]
        guide.exemplars = {
            "short/percussive": short_sample,
            "long/clausal": long_sample,
            "dialogue": " ".join(dialogue[:3]) if dialogue else "",
            "action": " ".join(action[:3]),
        }
    return guide


def style_fit(text: str, guide: StyleGuide) -> float:
    """How closely a candidate matches the guide: 1.0 = same habits, 0.0 = nothing alike."""

    def close(value: float, target: float, scale: float) -> float:
        return max(0.0, 1.0 - abs(value - target) / max(scale, 1e-6))

    sentences = _sentences(text)
    if not sentences:
        return 0.0
    words = len(text.split()) or 1
    n = len(sentences)
    lengths = [len(s.split()) for s in sentences]
    mean = sum(lengths) / n
    short = sum(1 for x in lengths if x <= 5) / n * 100
    questions = sum(1 for s in sentences if s.rstrip().endswith("?")) / n * 100
    exclam = text.count("!") * 1000 / words
    simile = len(_SIMILE.findall(text)) * 1000 / words

    scores = [
        close(mean, guide.mean_sentence_length, 10.0),
        close(short, guide.short_sentence_pct, 40.0),
        close(questions, guide.question_pct, 25.0),
        close(exclam, guide.exclamation_per_1k, 20.0),
        close(simile, guide.simile_per_1k, 12.0),
    ]
    return round(sum(scores) / len(scores), 4)


def save_guide(guide: StyleGuide, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(guide), indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def load_guide(path: str | Path) -> StyleGuide:
    return StyleGuide(**json.loads(Path(path).read_text(encoding="utf-8")))
