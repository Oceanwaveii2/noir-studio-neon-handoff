"""
Adversarial correction checks: cases a rewrite must never pass.

Combines the deterministic guards into one verdict for fixture-driven tests:
facts, introduced entities, personification, role swaps, number changes, altered quotes,
and world-state violations.
"""

from __future__ import annotations

import re
from typing import List

from ..guards import introduced_entities, personification_issues, preserves_facts

CAST = ("Rainee", "Francine", "Haley", "Stan", "Roger", "Steve")
VERBS = ("slapped", "kissed", "pushed", "grabbed", "shot", "hit", "told", "fucked", "yelled at", "pulled")
NUMBER_WORD = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10,
}


def _roles(text: str):
    found = []
    pattern = re.compile(rf"\b({'|'.join(CAST)})\s+({'|'.join(VERBS)})\s+({'|'.join(CAST)})\b", re.IGNORECASE)
    for match in pattern.finditer(text):
        found.append((match.group(1).lower(), match.group(2).lower(), match.group(3).lower()))
    return found


def _numbers(text: str):
    values = [int(value) for value in re.findall(r"\b\d+\b", text)]
    values += [NUMBER_WORD[word] for word in re.findall(r"\b\w+\b", text.lower()) if word in NUMBER_WORD]
    return sorted(values)


def _quotes(text: str):
    return re.findall(r'[\"\u201c]([^\"\u201d]{3,})[\"\u201d]', text)


def check(original: str, candidate: str, world=None) -> List[str]:
    issues: List[str] = []
    ok, missing = preserves_facts(original, candidate)
    if not ok:
        issues.append("drops facts: " + ", ".join(missing[:3]))

    new = introduced_entities(original, candidate, CAST)
    if new:
        issues.append("new entities: " + ", ".join(new[:3]))

    if personification_issues(candidate):
        issues.append("personification: " + "; ".join(personification_issues(candidate)[:2]))

    before, after = _roles(original), _roles(candidate)
    if before and after and before != after:
        issues.append("role swap")

    if _numbers(original) != _numbers(candidate):
        issues.append("number changed")

    for quote in _quotes(original):
        if quote not in candidate:
            issues.append("quoted speech altered")
            break

    if world is not None:
        breaks = world.violations(candidate) + world.plausibility(candidate)
        if breaks:
            issues.append("world state: " + "; ".join(f"{phrase} ({why})" for phrase, why in breaks[:2]))
    return issues
