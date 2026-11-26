"""
Per-passage strength: the DLSS knob for text.

A strength map assigns each paragraph a number from 0 to 1:

    0.00-0.15  frozen   — never touched
    0.15-0.45  light    — copy-edit, remove tells, keep sentences
    0.45-0.75  standard — rewrite in place
    0.75-1.00  rebuild  — write from the facts, new sentences

Selectors pick paragraphs by index, range, or content. First matching rule wins; `default`
applies to the rest. Frozen spans are exact strings that must survive the rewrite verbatim
(dialogue, names, a line you refuse to lose).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Sequence, Tuple


@dataclass(frozen=True)
class Policy:
    strength: float
    preset: str
    skip: bool


def policy(strength: float) -> Policy:
    strength = max(0.0, min(1.0, float(strength)))
    if strength <= 0.15:
        return Policy(strength, "light", True)
    if strength <= 0.45:
        return Policy(strength, "light", False)
    if strength <= 0.75:
        return Policy(strength, "standard", False)
    return Policy(strength, "rebuild", False)


@dataclass
class Rule:
    selector: str
    strength: float


@dataclass
class StrengthMap:
    default: float = 1.0
    rules: List[Rule] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "StrengthMap":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        rules = [Rule(item["selector"], float(item["strength"])) for item in data.get("rules", [])]
        return cls(default=float(data.get("default", 1.0)), rules=rules)

    @classmethod
    def uniform(cls, strength: float) -> "StrengthMap":
        return cls(default=strength)

    def strength_for(self, index: int, text: str) -> float:
        for rule in self.rules:
            if self._matches(rule.selector, index, text):
                return rule.strength
        return self.default

    def policy_for(self, index: int, text: str) -> Policy:
        return policy(self.strength_for(index, text))

    @staticmethod
    def _matches(selector: str, index: int, text: str) -> bool:
        selector = selector.strip()
        if selector in ("all", "*"):
            return True
        if selector.startswith("index:"):
            try:
                return index == int(selector.split(":", 1)[1])
            except ValueError:
                return False
        if selector.startswith("range:"):
            try:
                low, high = selector.split(":", 1)[1].split("-")
                return int(low) <= index <= int(high)
            except ValueError:
                return False
        if selector.startswith("contains:"):
            return selector.split(":", 1)[1].lower() in text.lower()
        if selector.startswith("not_contains:"):
            return selector.split(":", 1)[1].lower() not in text.lower()
        return False


def dialogue_lines(paragraphs: Sequence[str]) -> List[str]:
    """Exact dialogue paragraphs, for freeze lists."""
    return [part for part in paragraphs if part.strip().startswith(("-", "—", "“", '"'))]


def missing_frozen(original: str, candidate: str, frozen: Sequence[str]) -> List[str]:
    """Frozen spans present in the original that the candidate dropped or altered."""
    return [
        span
        for span in frozen
        if span.strip() and span.lower() in original.lower() and span.lower() not in candidate.lower()
    ]
