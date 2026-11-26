"""
Negation-aware canon rule matching.

`books/world_state.json` and `story_graph/ontology.py` both carry regex rules for
canon that the model is known to import from the source show (e.g. "Francine
Smith", "Stan Smith"). A blind regex ban also rejects the *canonical* divergences
("I didn't marry Stan", "Stan dumped her"), so these rules may opt into negation
awareness with:

    {"pattern": "...", "why": "...", "allow_negated": true, "negation_cues": [...]}

The sentence around a match is checked for a cue. If one is present, the match is
treated as a statement *about* the forbidden idea (a correction or negation)
rather than an assertion of it.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Sequence, Tuple

# Cues are deliberately specific. Bare "not" / "no" are excluded because they
# appear in unrelated clauses ("the Smith house was not empty") and would let a
# real import error through.
DEFAULT_NEGATION_CUES: Tuple[str, ...] = (
    "never",
    "didn't",
    "did not",
    "doesn't",
    "does not",
    "don't",
    "do not",
    "without",
    "dumped",
    "dumps",
    "broke up",
    "broken up",
    "left her",
    "ex-",
    "instead of",
    "rather than",
    "maiden name",
    "kept the ling name",
    "kept her ling name",
    "no smith",
    "not a smith",
    "never a smith",
    "before the wedding",
    "before they married",
)

_SENTENCE_END = ".!?;\n"


def sentence_window(text: str, start: int, end: int) -> str:
    """Returns the sentence containing [start, end), including the match."""
    left = max(text.rfind(ch, 0, start) for ch in _SENTENCE_END) + 1
    rights = [i for i in (text.find(ch, end) for ch in _SENTENCE_END) if i != -1]
    right = min(rights) if rights else len(text)
    return text[left:right]


def is_negated(
    text: str,
    match: re.Match[str],
    cues: Iterable[str] = DEFAULT_NEGATION_CUES,
) -> bool:
    window = sentence_window(text, match.start(), match.end()).lower()
    return any(cue in window for cue in cues)


def find_rule_violations(
    text: str,
    rules: Sequence[Dict[str, Any]],
) -> List[Tuple[Dict[str, Any], str]]:
    """Returns (rule, matched_text) for each rule match that is not excused.

    A rule may opt into two context checks:

    - ``allow_negated``: skip a match whose sentence contains a negation cue
      ("I didn't marry Stan").
    - ``allow_context``: skip a match whose sentence contains a listed simile or
      framing cue ("just Mom cosplaying as a cartoon dad").
    """
    found: List[Tuple[Dict[str, Any], str]] = []
    for rule in rules:
        pattern = str(rule.get("pattern") or "")
        if not pattern:
            continue

        cues: Iterable[str] = DEFAULT_NEGATION_CUES
        raw_cues = rule.get("negation_cues")
        if isinstance(raw_cues, (list, tuple)) and raw_cues:
            cues = tuple(str(c) for c in raw_cues)

        allow_context = rule.get("allow_context") or ()
        if isinstance(allow_context, str):
            allow_context = (allow_context,)
        allow_context = tuple(str(c).lower() for c in allow_context)

        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            window = sentence_window(text, match.start(), match.end()).lower()
            if allow_context and any(c in window for c in allow_context):
                continue
            if rule.get("allow_negated") and is_negated(text, match, cues):
                continue
            found.append((rule, match.group(0)))
    return found
