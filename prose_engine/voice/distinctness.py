"""
Distinctness for variation: semantic cosine + structural signature, selected with MMR.

The point is spread, not "best". Two takes that paraphrase the same beat are one take.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence, Tuple

WORD = re.compile(r"[A-Za-z']+")
SENTENCE = re.compile(r"[^.!?]+[.!?]")


def structural(text: str) -> Tuple:
    sentences = [segment.strip() for segment in SENTENCE.findall(text) if segment.strip()]
    words = WORD.findall(text)
    first = words[0].lower() if words else ""
    last = words[-1].lower() if words else ""
    return (
        len(sentences),
        first,
        last,
        text.count("—"),
        text.count("?"),
        text.count("!"),
        round(len(words) / max(1, len(sentences)), 1),
    )


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb + 1e-9)


@dataclass
class Take:
    text: str
    treatment: str
    vector: List[float] = None


def select(takes: List[Take], limit: int, max_similarity: float = 0.85) -> List[Take]:
    """Greedy MMR: keep the most distinct takes, never two near-duplicates."""
    chosen: List[Take] = []
    pool = list(takes)
    tokens = {id(t): tuple(re.findall(r"\w+", t.text.casefold())) for t in takes}
    while pool and len(chosen) < limit:
        best = None
        best_score = -1.0
        for take in pool:
            if not tokens[id(take)]:
                continue
            words = set(tokens[id(take)])
            if any(
                tokens[id(take)] == tokens[id(other)]
                or len(words & set(tokens[id(other)])) / len(words | set(tokens[id(other)])) >= max_similarity
                for other in chosen
            ):
                continue
            if chosen and take.vector is not None and all(t.vector is not None for t in chosen):
                closest = max(cosine(take.vector, other.vector) for other in chosen)
                if closest >= max_similarity:
                    continue
                spread = 1.0 - closest
            else:
                spread = 1.0 if not chosen else 0.0
            structural_bonus = 0.0 if not chosen else (1.0 if structural(take.text) != structural(chosen[-1].text) else 0.0)
            score = spread + 0.25 * structural_bonus
            if score > best_score:
                best, best_score = take, score
        if best is None:
            break
        chosen.append(best)
        pool.remove(best)
    return chosen
