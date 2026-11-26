"""
Rhythm transfer: match the cadence of the retrieved passages, not just their words.

Cosine similarity prefers familiar vocabulary. Cadence matching asks whether the rewrite moves
like the corpus: similar mean sentence length and similar sentence-length variation.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from .diagnostics import ProseDiagnosticsAnalyzer as D

Target = Tuple[float, float]


def cadence(text: str) -> Tuple[float, float]:
    sentences = D.split_into_sentences(text)
    if len(sentences) < 2:
        return (float(len(text.split())), 0.0)
    mean, sd = D.compute_cadence(sentences)
    return (float(mean), float(sd))


def rhythm_target(passages: Sequence[str], minimum_words: int = 20) -> Optional[Target]:
    usable = [p for p in passages if len(p.split()) >= minimum_words]
    if not usable:
        return None
    means = []
    sds = []
    for passage in usable:
        mean, sd = cadence(passage)
        means.append(mean)
        sds.append(sd)
    return (sum(means) / len(means), sum(sds) / len(sds))


def rhythm_match(text: str, target: Optional[Target]) -> float:
    """1.0 = cadence identical to the reference passages, 0.0 = far off."""
    if target is None:
        return 0.5
    mean, sd = cadence(text)
    target_mean, target_sd = target
    distance = (
        abs(mean - target_mean) / max(1.0, target_mean)
        + abs(sd - target_sd) / max(1.0, target_sd)
    ) / 2.0
    return max(0.0, 1.0 - distance)
