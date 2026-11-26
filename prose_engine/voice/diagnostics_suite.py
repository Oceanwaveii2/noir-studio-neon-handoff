"""
Contamination-free prose diagnostics.

Unlike corpus-centroid similarity (retracted as a target, see docs/RETRACTIONS.md), every metric
here is computed from the text itself, reports the spans it fired on, and can be compared to a
held-out human baseline.

    python -m prose_engine voice analyze --file scene.md
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from ..paths import books
from .tics import counts as tic_counts, scan as tic_scan

WORD = re.compile(r"[A-Za-z']+")
SENTENCE = re.compile(r"[^.!?]+[.!?]+")
SIMILE = re.compile(r"\b(?:like a|like an|like the|as if|as though)\b", re.IGNORECASE)
PARTICIPIAL = re.compile(r",\s+[a-z]+ing\b")
FILTER = re.compile(
    r"\b(?:noticed|notices|felt|feels|saw|sees|heard|hears|realized|realizes|seemed|seems|"
    r"watched|watches|thought|thinks|knew|knows|wondered|wonders)\b",
    re.IGNORECASE,
)
DIALOGUE = re.compile(r"^\s*(?:[-—\"“]|[A-Z][A-Za-z .'-]{0,24}:)")
PROPER = re.compile(r"\b[A-Z][a-z]{2,}\b")
NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\b")


@dataclass
class Diagnostic:
    rule: str
    count: int
    rate_per_1000: float
    examples: List[str] = field(default_factory=list)


def _load_cliches() -> List[str]:
    path = books("antislop.json")
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [entry[0] for entry in data.get("banlist", []) if entry and entry[0]]


def analyze(text: str) -> Dict:
    words = WORD.findall(text)
    total = max(1, len(words))
    sentences = [segment for segment in SENTENCE.findall(text) if segment.strip()]
    lengths = [len(WORD.findall(segment)) for segment in sentences] or [0]
    lines = [line for line in text.splitlines() if line.strip()]

    findings: List[Diagnostic] = []

    def add(rule: str, matches: List[str]) -> None:
        findings.append(
            Diagnostic(rule, len(matches), round(len(matches) / total * 1000, 2), matches[:3])
        )

    add("tic", [finding.excerpt for finding in tic_scan(text)])
    add("filter", FILTER.findall(text))
    add("simile", SIMILE.findall(text))
    add("participial", PARTICIPIAL.findall(text))
    add(
        "cliche",
        [phrase for phrase in _load_cliches() if phrase.lower() in text.lower()],
    )

    # repeated 4-grams inside the scene
    tokens = [word.lower() for word in words]
    grams = [" ".join(tokens[i:i + 4]) for i in range(len(tokens) - 3)]
    seen = {}
    for gram in grams:
        seen[gram] = seen.get(gram, 0) + 1
    repeated = [gram for gram, count in seen.items() if count > 1]
    add("repetition", repeated)

    dialogue = sum(1 for line in lines if DIALOGUE.match(line))
    proper = len(PROPER.findall(text))
    numbers = len(NUMBER.findall(text))
    import statistics

    return {
        "words": total,
        "sentences": len(sentences),
        "mean_sentence": round(statistics.mean(lengths), 2),
        "sd_sentence": round(statistics.pstdev(lengths), 2),
        "dialogue_ratio": round(dialogue / max(1, len(lines)), 3),
        "specificity_per_100": round((proper + numbers) / total * 100, 2),
        "findings": {
            finding.rule: {
                "count": finding.count,
                "rate_per_1000": finding.rate_per_1000,
                "examples": finding.examples,
            }
            for finding in findings
        },
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    text = Path(args.file).read_text(encoding="utf-8")
    result = analyze(text)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
