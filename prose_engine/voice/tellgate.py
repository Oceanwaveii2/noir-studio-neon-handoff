"""
Tell-gate: an Antislop-style frequency profiler for our own outputs.

Profiles 3-grams that are over-represented in generated text compared with the reference corpus
(ratio > threshold, minimum count), plus the measured participial/excess-lexicon counts. A
candidate is rejected if its tell density exceeds the gate.

    python tools/build_antislop.py
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from .tics import scan as tic_scan

WORD = re.compile(r"[A-Za-z']+")
NGRAM = 3

# Character and place names are story facts, not tells; exclude them from the banlist.
NAMES = {
    "rainee", "ling", "ma", "francine", "stella", "haley", "peter", "griffin",
    "baba", "nana", "papa", "fran", "deluxe", "ling's", "idolessa",
}


def _normalize(text: str) -> List[str]:
    return [word.lower() for word in WORD.findall(text)]


def _counts(texts: Iterable[str]) -> Counter:
    counter: Counter = Counter()
    for text in texts:
        words = _normalize(text)
        for index in range(len(words) - NGRAM + 1):
            counter[tuple(words[index : index + NGRAM])] += 1
    return counter


def build_profile(
    generated: Iterable[str],
    reference: Iterable[str],
    min_ratio: float = 6.0,
    min_count: int = 3,
    min_df: int = 3,
) -> Dict:
    gen_texts = list(generated)
    gen_counter = _counts(gen_texts)
    ref_list = list(reference)
    ref_counter = _counts(ref_list)
    ref_word_counts: Counter = Counter()
    for text in ref_list:
        ref_word_counts.update(_normalize(text))
    df: Counter = Counter()
    for text in gen_texts:
        words = _normalize(text)
        seen = {tuple(words[i : i + NGRAM]) for i in range(len(words) - NGRAM + 1)}
        df.update(seen)
    gen_total = max(1, sum(gen_counter.values()))
    ref_total = max(1, sum(ref_counter.values()))
    banlist: List[Tuple[str, float]] = []
    for ngram, count in gen_counter.items():
        if count < min_count or df.get(ngram, 0) < min_df:
            continue
        if any(word in NAMES for word in ngram):
            continue
        if any(ref_word_counts.get(word, 0) < 50 for word in ngram):
            continue
        ratio = (count / gen_total) / ((ref_counter.get(ngram, 0) + 0.5) / ref_total)
        if ratio >= min_ratio:
            banlist.append((" ".join(ngram), round(ratio, 1)))
    banlist.sort(key=lambda pair: -pair[1])
    return {"min_ratio": min_ratio, "min_count": min_count, "banlist": banlist[:400]}


def save_profile(profile: Dict, path: str | Path = "books/antislop.json") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return target


def load_profile(path: str | Path = "books/antislop.json") -> Dict:
    file = Path(path)
    return json.loads(file.read_text(encoding="utf-8")) if file.is_file() else {"banlist": []}


@dataclass
class TellReport:
    density: float
    hits: List[str]
    tics: Dict[str, int]

    def ok(self, limit: float) -> bool:
        return self.density <= limit


def score(text: str, profile: Dict) -> TellReport:
    lowered = " " + " ".join(_normalize(text)) + " "
    hits = [phrase for phrase, _ratio in profile.get("banlist", []) if f" {phrase} " in lowered]
    words = max(1, len(_normalize(text)))
    tic_counts = {}
    for finding in tic_scan(text):
        tic_counts[finding.rule] = tic_counts.get(finding.rule, 0) + 1
    tic_terms = sum(tic_counts.values())
    density = (len(hits) + 0.5 * tic_terms) / words * 1000
    return TellReport(round(density, 2), hits[:12], tic_counts)
