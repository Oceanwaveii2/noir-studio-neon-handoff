"""
Real-Time Neural Slop & Anti-AI-ism Coprocessor.
Milestone CP-3: Real-Time Neural Slop & Anti-AI-ism Coprocessor.

Focuses strictly on literary quality and natural human cadence without crippling
storytelling with copyright or plagiarism n-gram hard blocks:
  1. Anti-AI Tell Gate: Flags mechanical AI binary contrasts ('less X and more Y'),
     essayistic transitions ('Because of this'), symmetrical tripartite verbs,
     and stock melodrama clichés ('white-knuckles', 'quivering jaw', 'pale blush').
  2. Stylistic Cadence Gate: Computes standard deviation of sentence lengths (burstiness >= 4.0)
     to ensure lively, rhythmic human storytelling over flat LLM monotony.
  3. Non-Blocking Informational Tracking: Plagiarism / n-gram shingle checks are never
     hard gates; they never reject or cripple creative prose.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..guards import copy_issues
from ..linter import AntiAILinter, LinterReport


@dataclass
class GuardrailAuditReport:
    passed: bool
    is_clean_of_ai_tells: bool
    burstiness_passed: bool
    burstiness_score: float
    ai_tell_violations: List[str]
    informational_reference_matches: List[str] = field(default_factory=list)
    is_clean_of_ontological_breaches: bool = True
    ontological_violations: List[str] = field(default_factory=list)

    # Backward compatibility properties
    @property
    def is_clean_of_plagiarism(self) -> bool:
        return len(self.informational_reference_matches) == 0

    @property
    def plagiarism_issues(self) -> List[str]:
        return self.informational_reference_matches

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["is_clean_of_plagiarism"] = self.is_clean_of_plagiarism
        data["plagiarism_issues"] = self.plagiarism_issues
        return data


class GuardrailCoprocessor:
    """
    Sub-second coprocessor focused purely on anti-slop, natural literary cadence,
    and anti-AI tell detection, leaving creative prose unconstrained by copyright blocks.
    """

    def __init__(self, linter: Optional[AntiAILinter] = None):
        self.linter = linter or AntiAILinter()

    def audit_text(
        self,
        candidate_text: str,
        reference_passages: Optional[Sequence[str]] = None,
        burstiness_threshold: float = 4.0,
        enforce_plagiarism_blocking: bool = False,
        ontology_negative_rules: Optional[Sequence[Dict[str, str]]] = None,
        character_morph_permissions: Optional[Dict[str, bool]] = None,
    ) -> GuardrailAuditReport:
        """
        Executes a rapid, sub-second screen of candidate prose.
        Focuses strictly on literary vitality, anti-AI cleanliness, and ontological invariants.
        Plagiarism checks are purely informational and do not fail the audit by default.
        """
        # 1. Informational Reference Tracking (Non-blocking)
        ref_matches: List[str] = []
        if reference_passages:
            ref_matches = copy_issues(candidate_text, reference_passages, ngram=5)

        # 2. Anti-AI Tells & Burstiness (The Real Quality Gates)
        linter_report = self.linter.lint(candidate_text, burstiness_threshold=burstiness_threshold)
        is_clean_ai = (linter_report.total_violations == 0)

        ai_violations = [
            f"L{v.line_number} [{v.category}]: '{v.matched_text}'"
            for v in linter_report.violations
        ]

        # 3. Real-Time Ontological Invariant Scan (negation- & context-aware)
        from ..canon_rules import find_rule_violations
        from ..canon_guard import canon_conflicts, format_finding

        onto_violations: List[str] = []
        if ontology_negative_rules:
            for rule, matched in find_rule_violations(candidate_text, ontology_negative_rules):
                onto_violations.append(
                    f"ONTOLOGY_BREACH [{rule.get('id', 'rule')}]: '{matched}' — {rule.get('why', '')}"
                )

        if character_morph_permissions:
            for char, allowed in character_morph_permissions.items():
                if not allowed:
                    pat = rf"\b{re.escape(char)}\b[^.?!;]{{0,60}}\b(morph(?:s|ed|ing)?|shapeshift(?:s|ed|ing)?|transform(?:s|ed|ing)?|grows?\s+a?\s*(?:tail|ears?))\b"
                    if re.search(pat, candidate_text, re.IGNORECASE):
                        onto_violations.append(f"MORPH_BREACH: Character '{char}' cannot shapeshift.")

        # Also validate against compiled accumulative state when ontology or AFM morph matrix is active.
        if ontology_negative_rules is not None or character_morph_permissions is not None:
            seen_evidence = {v.lower() for v in onto_violations}
            for finding in canon_conflicts(candidate_text):
                msg = format_finding(finding)
                if not any(finding.evidence.lower() in existing for existing in seen_evidence):
                    onto_violations.append(f"CANON_STATE_BREACH {msg}")
                    seen_evidence.add(msg.lower())

        is_clean_ontology = (len(onto_violations) == 0)

        # Storytelling Priority: AI tells, flat cadence, and ontological breaches gate the text.
        overall_passed = is_clean_ai and linter_report.burstiness_passed and is_clean_ontology
        if enforce_plagiarism_blocking and len(ref_matches) > 0:
            overall_passed = False

        return GuardrailAuditReport(
            passed=overall_passed,
            is_clean_of_ai_tells=is_clean_ai and is_clean_ontology,
            burstiness_passed=linter_report.burstiness_passed,
            burstiness_score=linter_report.burstiness_score,
            ai_tell_violations=ai_violations + onto_violations,
            informational_reference_matches=ref_matches,
            is_clean_of_ontological_breaches=is_clean_ontology,
            ontological_violations=onto_violations,
        )
