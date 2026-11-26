"""
Fusion instead of selection.

Selection assumes a scorer that correlates with quality; at ρ≈0.12 it does not. Fusion gives the
model several drafts and asks it to synthesize one paragraph against a fixed rubric, keeping what
each draft got right. The fused text is then gated like any other candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .best_of_n import score_text
from .critique import collect

RUBRIC = [
    "keep every name, number, and quoted line from the facts",
    "sound like the reference books: their rhythm, diction and sentence shapes",
    "use none of the original's comparisons, reworded or not",
    "vary sentence lengths; no tic pileup (participial tails, excess lexicon)",
    "read as one scene, not a summary",
]


@dataclass
class FusionResult:
    text: str = ""
    drafts: List[str] = field(default_factory=list)
    score: float = 0.0
    accepted: bool = False
    reason: str = ""
    issues: List[str] = field(default_factory=list)


def rubric_block() -> str:
    return "RUBRIC (all five):\n" + "\n".join(f"{number}. {item}" for number, item in enumerate(RUBRIC, 1))


def fusion_prompt(original: str, drafts: List[str]) -> str:
    numbered = "\n\n".join(f"DRAFT {index}:\n{text}" for index, text in enumerate(drafts, 1))
    return (
        "Three drafts of the same paragraph are below. Write ONE final paragraph that takes the "
        "best of them and satisfies the rubric. Do not merge them mechanically; rewrite.\n\n"
        f"ORIGINAL FACTS (must survive):\n{original}\n\n{numbered}\n\n{rubric_block()}\n\n"
        "Return only the final paragraph."
    )


class Fusion:
    def __init__(self, provider, evaluator=None, style_model=None, drafts: int = 3):
        self.provider = provider
        self.evaluator = evaluator
        self.style_model = style_model
        self.drafts = drafts

    def run(self, original: str, prompt: str, request, contract=None, bible=None, ledger=None,
            pov: str = "", max_overlap: float = 0.45) -> FusionResult:
        from ..guards import preserves_facts, token_overlap

        result = FusionResult()
        for _ in range(self.drafts):
            try:
                draft = self.provider.generate_rewrite(request, prompt)
            except Exception:
                continue
            if draft and draft.strip():
                result.drafts.append(draft.strip())
        if not result.drafts:
            result.reason = "no drafts generated"
            return result

        try:
            fused = self.provider.generate_rewrite(request, fusion_prompt(original, result.drafts))
        except Exception:
            fused = ""
        text = (fused or "").strip()
        if not text:
            text = max(result.drafts, key=len)
            result.reason = "synthesis failed; longest draft kept"

        issues = collect(text, contract=contract, bible=bible, ledger=ledger, pov=pov,
                         style_model=self.style_model)
        hard = {issue.rule for issue in issues}
        ok, missing = preserves_facts(original, text)
        overlap = token_overlap(original, text)
        result.text = text
        result.issues = sorted(hard)
        if not ok:
            result.reason = "drops facts: " + ", ".join(missing[:3])
        elif overlap > max_overlap:
            result.reason = f"overlap {overlap:.2f} > {max_overlap:.2f}"
        elif hard:
            result.reason = "unresolved: " + ", ".join(sorted(hard)[:4])
        else:
            result.accepted = True
            result.reason = result.reason or "ok"
        return result
