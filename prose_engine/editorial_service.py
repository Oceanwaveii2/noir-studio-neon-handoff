"""Read-only proposal preview. Offsets are Python Unicode code-point offsets."""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass

from .canon_rules import find_rule_violations
from .voice.world_state import WorldState


@dataclass(frozen=True)
class Edit:
    span_id: str
    start: int
    end: int
    expected: str
    replacement: str
    operation: str = "replace_span"


@dataclass(frozen=True)
class Issue:
    rule: str
    start: int
    end: int
    matched: str
    reason: str


@dataclass(frozen=True)
class Preview:
    status: str
    original: str
    candidate: str
    baseline_issues: tuple[Issue, ...]
    new_issues: tuple[Issue, ...] = ()
    author_decision: str = "pending"


def revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def issues(text: str, world: WorldState) -> tuple[Issue, ...]:
    """Locate every canon occurrence using the existing negation-aware rule logic."""
    result = []
    for index, rule in enumerate(world.banned):
        pattern = str(rule.get("pattern") or "")
        if not pattern:
            continue
        valid = Counter(matched for _, matched in find_rule_violations(text, [rule]))
        for match in re.finditer(pattern, text, re.IGNORECASE):
            # Re-evaluate each occurrence in its original context; duplicate matches
            # can differ in negation, so a count alone cannot establish location.
            from .canon_rules import DEFAULT_NEGATION_CUES, is_negated, sentence_window
            context = rule.get("allow_context") or ()
            context = (context,) if isinstance(context, str) else context
            window = sentence_window(text, match.start(), match.end()).lower()
            cues = rule.get("negation_cues") or DEFAULT_NEGATION_CUES
            if any(str(c).lower() in window for c in context):
                continue
            if rule.get("allow_negated") and is_negated(text, match, cues):
                continue
            if valid[match.group(0)] <= 0:
                continue
            valid[match.group(0)] -= 1
            result.append(Issue(str(rule.get("id") or f"banned:{index}"), match.start(), match.end(),
                                match.group(0), str(rule.get("why", "breaks canon"))))
    for index, rule in enumerate(world.impossible):
        pattern = str(rule.get("pattern") or "")
        if pattern:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                result.append(Issue(str(rule.get("id") or f"impossible:{index}"), match.start(),
                                    match.end(), match.group(0), str(rule.get("why", "not possible here"))))
    return tuple(sorted(result, key=lambda item: (item.start, item.end, item.rule)))


def preview(text: str, base_revision: str, edits: tuple[Edit, ...],
            frozen: tuple[tuple[int, int], ...], world: WorldState) -> Preview:
    baseline = issues(text, world)

    def reject(status: str) -> Preview:
        return Preview(status, text, text, baseline)

    if revision(text) != base_revision:
        return reject("STALE_REVISION")
    if not edits or any(not isinstance(e, Edit) or not e.span_id for e in edits):
        return reject("INVALID_EDIT")
    if len({e.span_id for e in edits}) != len(edits):
        return reject("DUPLICATE_SPAN_ID")
    if any(e.operation not in ("replace_span", "delete") for e in edits):
        return reject("UNSUPPORTED_OPERATION")
    if any(type(e.start) is not int or type(e.end) is not int or not 0 <= e.start < e.end <= len(text)
           or not isinstance(e.expected, str) or not isinstance(e.replacement, str)
           or (e.operation == "delete" and e.replacement) for e in edits):
        return reject("INVALID_RANGE")
    if any(type(a) is not int or type(b) is not int or not 0 <= a < b <= len(text) for a, b in frozen):
        return reject("INVALID_FROZEN_RANGE")
    ordered = sorted(edits, key=lambda e: e.start)
    if any(a.end > b.start for a, b in zip(ordered, ordered[1:])):
        return reject("OVERLAPPING_EDITS")
    if any(text[e.start:e.end] != e.expected for e in ordered):
        return reject("EXPECTED_TEXT_MISMATCH")
    if any(e.start < b and a < e.end for e in ordered for a, b in frozen):
        return reject("BLOCKED_FROZEN_SPAN")

    candidate = text
    for edit in reversed(ordered):
        candidate = candidate[:edit.start] + edit.replacement + candidate[edit.end:]
    old = set()
    for issue in baseline:
        if any(e.start < issue.end and issue.start < e.end for e in ordered):
            continue  # Conservatively treat issues within edited text as new.
        shift = sum(len(e.replacement) - (e.end - e.start) for e in ordered if e.end <= issue.start)
        old.add((issue.rule, issue.start + shift, issue.end + shift, issue.matched))
    new = tuple(i for i in issues(candidate, world) if (i.rule, i.start, i.end, i.matched) not in old)
    return Preview("BLOCKED_NEW_CANON_ISSUE" if new else "ELIGIBLE_FOR_REVIEW",
                   text, candidate, baseline, new)
