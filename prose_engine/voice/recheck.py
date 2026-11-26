"""Whole-document re-check: what the document looks like after edits, not just per paragraph."""

from __future__ import annotations

from typing import List, Optional


def document_issues(text: str, world=None, house=None, plan=None) -> List[str]:
    from ..conditioner import paragraph_spans

    issues: List[str] = []
    if world is not None:
        issues.extend(f"canon: {phrase} ({why})" for phrase, why in world.violations(text))
        issues.extend(f"canon: {phrase} ({why})" for phrase, why in world.plausibility(text))
    if house is not None:
        chunks = [text[start:end].strip() for start, end in paragraph_spans(text)]
        issues.extend(f"staging: {issue}" for issue in house.check_scene(chunks))
    if plan is not None:
        from .ledger import sections

        result = plan.validate(sections(text))
        issues.extend(f"ledger: {issue}" for issue in result["issues"])
    return issues
