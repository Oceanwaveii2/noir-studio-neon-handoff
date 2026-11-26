"""
Best-of-N: sample several rewrites, score them, keep the best only if it wins by a margin.

Scoring is the same four signals the rest of the engine trusts: corpus similarity, style distance,
tic count, and overlap with the original. With a margin, two near-identical candidates can't
sneak through as "different".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ..providers.deepseek import BudgetExceeded
from .tics import counts as tic_counts

WEIGHTS = {"tics": 0.55, "overlap": 0.25, "brevity": 0.20}


@dataclass
class Candidate:
    text: str
    score: float = 0.0
    parts: Dict[str, float] = field(default_factory=dict)


def voice_norm(cosine: Optional[float], similarity: float) -> float:
    """LUAR cosine to the book corpus, squeezed into 0-1; fall back to MiniLM similarity."""
    if cosine is None:
        return max(0.0, min(1.0, similarity))
    return max(0.0, min(1.0, (cosine - 0.2) / 0.6))


def score_text(
    text: str,
    similarity: float,
    style: float,
    overlap: float,
    base_style: Optional[float] = None,
    voice: Optional[float] = None,
    *,
    slop_quality: Optional[float] = None,
    slop_score: Optional[float] = None,
    slop_weight: float = 0.0,
) -> Candidate:
    words = max(1, len(text.split()))
    tic_total = sum(tic_counts(text).values())
    tic_rate = min(1.0, tic_total / words * 1000 / 10)
    # Absolute closeness matters; a zero gain against the original should not zero the term.
    style_norm = max(0.0, 1.0 - style / 4.0)
    brevity = min(1.0, 120 / max(1, words))
    parts = {
        "tics": round(1.0 - tic_rate, 4),
        "overlap": round(1.0 - min(1.0, overlap), 4),
        "brevity": round(brevity, 4),
        # diagnostics only; no longer part of the total
        "voice": round(voice_norm(voice, similarity), 4),
        "style": round(style_norm, 4),
        "similarity": round(similarity, 4),
    }
    total = sum(WEIGHTS[key] * parts[key] for key in WEIGHTS)
    if slop_quality is not None:
        sq = max(0.0, min(1.0, float(slop_quality)))
        parts["slop_quality"] = round(sq, 4)
        if slop_score is not None:
            parts["slop_score"] = round(float(slop_score), 2)
        if slop_weight > 0.0:
            w = max(0.0, min(1.0, float(slop_weight)))
            total = (1.0 - w) * total + w * sq
    return Candidate(text=text, score=round(total, 4), parts=parts)


def select_all(
    candidates: Sequence[Candidate], margin: float = 0.03, min_score: float = 0.0
) -> List[Candidate]:
    """Best candidate(s): a close call returns both for the author to choose."""
    ranked = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    if not ranked or ranked[0].score < min_score:
        return []
    best = ranked[0]
    if len(ranked) > 1:
        lead = best.score - ranked[1].score
        best.parts["lead"] = round(lead, 4)
        best.parts["margin_ok"] = 1.0 if lead >= margin else 0.0
        if lead < margin:
            best.parts["tie"] = 1.0
            ranked[1].parts["tie"] = 1.0
            return [best, ranked[1]]
    return [best]


def select(
    candidates: Sequence[Candidate], margin: float = 0.03, min_score: float = 0.0
) -> Optional[Candidate]:
    """Best candidate clearing min_score. When lead < margin, tie-break by lower overlap then shorter length."""
    ranked = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    if not ranked or ranked[0].score < min_score:
        return None
    best = ranked[0]
    if len(ranked) > 1:
        lead = best.score - ranked[1].score
        best.parts["lead"] = round(lead, 4)
        best.parts["margin_ok"] = 1.0 if lead >= margin else 0.0
        if lead < margin:
            best.parts["tie"] = 1.0
            ranked[1].parts["tie"] = 1.0
            tied = [c for c in ranked if (best.score - c.score) < margin]
            tied_sorted = sorted(
                tied,
                key=lambda c: (
                    -c.parts.get("overlap", 0.0),
                    len(c.text.split()),
                ),
            )
            return tied_sorted[0]
    return best


class BestOfN:
    def __init__(self, evaluator, style_model=None, margin: float = 0.03, voice=None, slop_critic=None, slop_weight: float = 0.25):
        self.evaluator = evaluator
        self.style_model = style_model
        self.margin = margin
        self.voice = voice
        self.slop_critic = slop_critic
        self.slop_weight = slop_weight

    def run(self, provider, request, prompt: str, n: int = 8, base_style: Optional[float] = None) -> List[Candidate]:
        from ..guards import token_overlap
        from ..styleprint import distance, fingerprint

        candidates: List[Candidate] = []
        self.errors: List[str] = []
        for _ in range(n):
            try:
                text = provider.generate_rewrite(request, prompt)
            except BudgetExceeded:
                raise
            except Exception as exc:
                self.errors.append(f"{type(exc).__name__}: {exc}"[:200])
                continue
            if not text or not text.strip():
                continue
            style = distance(fingerprint(text), self.style_model) if self.style_model else 0.0
            overlap = token_overlap(request.original_text, text)
            voice = self.voice.score(text) if self.voice is not None else None
            slop_quality = None
            slop_score = None
            if self.slop_critic is not None:
                crit = self.slop_critic.critique(text)
                slop_quality = crit.quality_bonus if crit.passed else 0.0
                slop_score = crit.slop_score
            candidates.append(
                score_text(
                    text,
                    similarity=self.evaluator.similarity(text),
                    style=style,
                    overlap=overlap,
                    base_style=base_style,
                    voice=voice,
                    slop_quality=slop_quality,
                    slop_score=slop_score,
                    slop_weight=self.slop_weight if self.slop_critic is not None else 0.0,
                )
            )
        return candidates
