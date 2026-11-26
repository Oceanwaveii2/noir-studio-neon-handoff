"""
Pipeline: retrieve → prompt → N candidates → select → critique once → gate → record.

The pipeline never trains and never silently accepts: every paragraph ends with a decision in the
ledger, including the reason it was rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .best_of_n import BestOfN, Candidate, select
from .critique import Issue, collect, revise
from .evaluate import Decision, Evaluator
from .tics import counts as tic_counts

HARD = {
    "reference_copy", "missing_fact", "forbidden", "forbidden_claim", "pov_absent",
    "known_information_forgetting", "style_drift",
}


@dataclass
class Result:
    text: str = ""
    accepted: bool = False
    reason: str = ""
    score: float = 0.0
    candidates: int = 0
    overlap: float = 0.0
    issues: List[str] = field(default_factory=list)


class Pipeline:
    def __init__(
        self,
        provider,
        evaluator: Evaluator,
        style_model=None,
        candidates: int = 8,
        margin: float = 0.03,
        min_score: float = 0.45,
        ledger: str | Path = "eval/decisions.jsonl",
        voice=None,
    ):
        self.provider = provider
        self.evaluator = evaluator
        self.style_model = style_model
        self.candidates = candidates
        self.margin = margin
        self.min_score = min_score
        self.ledger = Path(ledger)
        self.voice = voice

    def rewrite(
        self,
        original: str,
        prompt: str,
        request,
        contract=None,
        bible=None,
        ledger=None,
        pov: str = "",
        scene: str = "",
        paragraph: int = 0,
        max_overlap: float = 0.45,
        revise_once: bool = True,
        references=()
    ) -> Result:
        from ..guards import preserves_facts, token_overlap
        from ..styleprint import distance, fingerprint

        base_style = distance(fingerprint(original), self.style_model) if self.style_model else 0.0
        pool: List[Candidate] = BestOfN(
            self.evaluator, self.style_model, self.margin, voice=getattr(self, "voice", None)
        ).run(self.provider, request, prompt, n=self.candidates, base_style=base_style)

        # hard gates before ranking: facts gate and blacklist cliché gate (no paranoid reference copy-guards)
        from ..guards import preserves_facts
        from .tics import blacklisted_cliches

        generated = len(pool)
        facts_dropped = sum(1 for c in pool if not preserves_facts(original, c.text)[0])
        cliches_dropped = sum(1 for c in pool if blacklisted_cliches(c.text))
        gated = [
            candidate
            for candidate in pool
            if preserves_facts(original, candidate.text)[0]
            and not blacklisted_cliches(candidate.text)
        ]
        pool = gated
        self.last_pool = [
            {"text": candidate.text, "score": candidate.score, "parts": candidate.parts}
            for candidate in pool
        ]
        chosen = select(pool, self.margin, self.min_score)
        result = Result(candidates=generated)
        if chosen is None:
            if generated and not pool:
                if cliches_dropped:
                    result.reason = f"all {generated} candidates contained blacklisted AI clichés"
                elif facts_dropped:
                    result.reason = f"drops facts: all {generated} candidates dropped facts"
                else:
                    result.reason = f"all {generated} candidates dropped by hard gates"
            else:
                result.reason = (
                    "no candidate cleared the score floor" if pool else "no candidates generated"
                )
            self._record(result, original, scene, paragraph)
            return result

        text = chosen.text
        warnings = []
        from ..guards import personification_issues

        roles = personification_issues(text)
        if roles:
            result.text = text
            result.reason = "coherence: " + "; ".join(roles[:2])
            self._record(result, original, scene, paragraph)
            return result
        issues = warnings + collect(
            text, contract=contract, bible=bible, ledger=ledger, pov=pov,
            style_model=self.style_model, base_style=base_style,
        )
        if revise_once and issues:
            revised = revise(self.provider, request, text, issues)
            if revised and revised != text:
                revised_score = BestOfN(self.evaluator, self.style_model, self.margin).run(
                    _Once(revised), request, prompt, n=1, base_style=base_style
                )
                if revised_score and revised_score[0].score > chosen.score:
                    text, chosen = revised, revised_score[0]
                    issues = collect(
                        text, contract=contract, bible=bible, ledger=ledger, pov=pov,
                        style_model=self.style_model, base_style=base_style,
                    )

        result.text = text
        result.score = chosen.score
        result.issues = [issue.rule for issue in issues]

        ok, missing = preserves_facts(original, text)
        overlap = token_overlap(original, text)
        result.overlap = overlap
        hard = [issue for issue in issues if issue.rule in HARD]
        if not ok:
            result.reason = "drops facts: " + ", ".join(missing[:3])
        elif overlap > max_overlap:
            result.reason = f"overlap {overlap:.2f} > {max_overlap:.2f}"
        elif hard:
            result.reason = "unresolved: " + ", ".join(sorted({issue.rule for issue in hard})[:4])
        else:
            result.accepted = True
            result.reason = "ok"
        self._record(result, original, scene, paragraph)
        return result

    def _record(self, result: Result, original: str, scene: str, paragraph: int) -> None:
        import time
        decision = Decision(
            scene=scene or "scene",
            paragraph=paragraph,
            accepted=result.accepted,
            reason=result.reason or ("ok" if result.accepted else "rejected"),
            similarity=self.evaluator.similarity(result.text or original),
            percentile=self.evaluator.percentile(result.text or original),
            overlap=result.overlap,
            tics=tic_counts(result.text or original),
            candidates=result.candidates,
            provider=getattr(self.provider, "model_name", ""),
            model=getattr(self.provider, "model_name", ""),
            task="pipeline",
            gates={"issues": result.issues, "accepted": result.accepted},
            ts_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self.evaluator.record(decision, self.ledger)


class _Once:
    """Provider that returns one fixed text (for scoring a revised candidate)."""

    model_name = "once"

    def __init__(self, text: str):
        self.text = text

    def generate_rewrite(self, request, prompt):  # noqa: ARG002
        return self.text
