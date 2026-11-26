"""Deterministic SlopCritic gate and scorer unifying slop rules, AntiAILinter, tics, and optional SlopModel (Epic 5)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from ..canon_rules import is_negated
from ..linter import AntiAILinter
from ..paths import books
from .slop import SlopModel, flag as flag_slop_spans
from .tics import blacklisted_cliches


_QUOTE_MASK = re.compile(r'"[^"]*"|\u201c[^\u201d]*\u201d|\'[^\'\n]{4,}\'')
_SENTENCE_SPLIT = re.compile(r"[.!?]+")


def _mask_dialogue(text: str) -> str:
    return _QUOTE_MASK.sub(lambda m: " " * len(m.group(0)), text)


@dataclass
class SlopCritique:
    """Structured deterministic quality audit for one prose candidate."""

    passed: bool
    slop_score: float
    quality_bonus: float
    hard_blocks: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    spans: List[Dict[str, Any]] = field(default_factory=list)
    anti_ai_issues: List[Dict[str, Any]] = field(default_factory=list)
    cliches: List[str] = field(default_factory=list)
    burstiness: float = 0.0
    burstiness_passed: bool = True
    model_used: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "slop_score": self.slop_score,
            "quality_bonus": self.quality_bonus,
            "hard_blocks": list(self.hard_blocks),
            "warnings": list(self.warnings),
            "spans": list(self.spans),
            "anti_ai_issues": list(self.anti_ai_issues),
            "cliches": list(self.cliches),
            "burstiness": self.burstiness,
            "burstiness_passed": self.burstiness_passed,
            "model_used": self.model_used,
        }


class SlopCritic:
    """Deterministic critic replacing fragile LLM self-critics for slop and AI-tell gating."""

    def __init__(
        self,
        *,
        model_path: Optional[str | Path] = None,
        slop_model: Optional[SlopModel] = None,
        use_saved_model: bool = True,
        max_slop_score: float = 65.0,
        max_linter_violations: int = 3,
        burstiness_threshold: float = 4.0,
        require_burstiness: bool = False,
    ):
        self.max_slop_score = float(max_slop_score)
        self.max_linter_violations = int(max_linter_violations)
        self.burstiness_threshold = float(burstiness_threshold)
        self.require_burstiness = bool(require_burstiness)
        self.linter = AntiAILinter()
        self.slop_model = slop_model
        if self.slop_model is None and use_saved_model:
            candidate_path = Path(model_path) if model_path is not None else books("slop_model.json")
            if candidate_path.is_file():
                try:
                    self.slop_model = SlopModel.load(candidate_path)
                except Exception as exc:
                    raise RuntimeError(f"Failed to load configured SlopModel at {candidate_path}: {exc}") from exc

    def critique(self, text: str) -> SlopCritique:
        if not isinstance(text, str) or not text.strip():
            return SlopCritique(
                passed=False,
                slop_score=100.0,
                quality_bonus=0.0,
                hard_blocks=["Candidate text is empty."],
                burstiness_passed=False,
            )

        masked = _mask_dialogue(text)
        raw_spans = flag_slop_spans(text)

        # Exempt negated divergence spans for forbidden_smith just like CanonRules
        kept_spans = []
        hard_blocks: List[str] = []
        warnings: List[str] = []
        for sp in raw_spans:
            if sp.rule == "forbidden_smith":
                exact_match = next(
                    (m for m in re.finditer(re.escape(sp.text), text) if m.start() == sp.start),
                    None,
                )
                if exact_match is not None and is_negated(text, exact_match):
                    continue
                hard_blocks.append(f"Forbidden canon relapse: {sp.text}")
            kept_spans.append(sp)
            if sp.weight >= 4.0:
                warnings.append(f"{sp.rule}: {sp.text} ({sp.why})")

        cliches = blacklisted_cliches(masked)
        for cliche in cliches:
            hard_blocks.append(f"Blacklisted AI cliche: {cliche}")

        report = self.linter.lint(masked, burstiness_threshold=self.burstiness_threshold)
        sentences = [s for s in _SENTENCE_SPLIT.split(text) if len(s.split()) >= 2]
        burst_ok = report.burstiness_passed or len(sentences) < 3
        if self.require_burstiness and not burst_ok:
            hard_blocks.append(
                f"Low sentence burstiness ({report.burstiness_score:.2f} < {self.burstiness_threshold:.2f})."
            )

        # Density-normalize stylistic spans and linter counts by passage length
        # (baseline 350 words so short paragraphs stay strict while full chapters
        # are judged on slop density rather than raw word volume).
        word_count = max(1, len(text.split()))
        length_scale = max(1.0, word_count / 350.0)
        effective_max_violations = max(
            self.max_linter_violations,
            int(round(self.max_linter_violations * length_scale)),
        )
        if report.total_violations > effective_max_violations:
            hard_blocks.append(
                f"Excessive Anti-AI linter violations ({report.total_violations} > {effective_max_violations})."
            )

        span_weight_sum = sum(float(sp.weight) for sp in kept_spans)
        normalized_span_weight = span_weight_sum / length_scale
        normalized_violations = report.total_violations / length_scale
        normalized_cliches = len(cliches) / length_scale
        rule_score = min(
            100.0,
            normalized_span_weight * 5.0 + normalized_violations * 12.0 + normalized_cliches * 25.0,
        )
        model_used = self.slop_model is not None
        if self.slop_model is not None:
            model_score = float(self.slop_model.score(text))
            slop_score = round(0.45 * model_score + 0.55 * rule_score, 2)
        else:
            slop_score = round(rule_score, 2)

        if slop_score > self.max_slop_score:
            hard_blocks.append(f"Slop score {slop_score:.1f} exceeded cap {self.max_slop_score:.1f}.")

        base_bonus = max(0.0, min(1.0, (100.0 - slop_score) / 100.0))
        if report.burstiness_score >= 4.0 and len(sentences) >= 3:
            base_bonus = min(1.0, base_bonus + 0.05)

        return SlopCritique(
            passed=len(hard_blocks) == 0,
            slop_score=slop_score,
            quality_bonus=round(base_bonus, 4),
            hard_blocks=hard_blocks,
            warnings=warnings,
            spans=[asdict(sp) for sp in kept_spans],
            anti_ai_issues=[v.to_dict() for v in report.violations],
            cliches=cliches,
            burstiness=report.burstiness_score,
            burstiness_passed=burst_ok,
            model_used=model_used,
        )
