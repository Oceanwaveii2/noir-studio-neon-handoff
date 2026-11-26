"""
External-feedback critique.

Only structured signals produce issues: tic scan, scene contract, bible, ledger, style distance.
Never "improve this" — the research is unambiguous that free-form self-critique degrades text.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .tics import scan as tic_scan


@dataclass
class Issue:
    rule: str
    detail: str
    severity: str = "warning"

    def line(self) -> str:
        return f"- [{self.rule}] {self.detail}"


def collect(
    text: str,
    contract=None,
    bible=None,
    ledger=None,
    pov: str = "",
    style_model=None,
    base_style: Optional[float] = None,
    max_style_delta: float = 0.75,
) -> List[Issue]:
    issues: List[Issue] = []
    for finding in tic_scan(text):
        issues.append(Issue(finding.rule, finding.excerpt, finding.severity))
    if contract is not None:
        issues.extend(Issue(v.rule, v.detail) for v in contract.check(text))
    if bible is not None:
        issues.extend(Issue(v.rule, v.detail) for v in bible.check(text))
    if ledger is not None and pov:
        issues.extend(Issue(v.rule, v.detail) for v in ledger.check(pov, text))
    if style_model is not None:
        from ..styleprint import distance, fingerprint

        delta = distance(fingerprint(text), style_model) - (base_style or 0.0)
        if delta > max_style_delta:
            issues.append(Issue("style_drift", f"+{delta:.2f} from the corpus"))
    return issues


def prompt_for(issues: List[Issue], original: str) -> str:
    if not issues:
        return ""
    return (
        "FIX ONLY THESE ISSUES. Keep every fact and the voice; do not add events.\n"
        + "\n".join(issue.line() for issue in issues[:12])
        + "\n\nParagraph:\n"
        + original
    )


def revise(provider, request, text: str, issues: List[Issue]) -> str:
    prompt = prompt_for(issues, text)
    if not prompt:
        return text
    from ..providers.deepseek import BudgetExceeded

    try:
        candidate = provider.generate_rewrite(request, prompt)
    except BudgetExceeded:
        raise
    except Exception:
        return text
    return candidate.strip() or text
