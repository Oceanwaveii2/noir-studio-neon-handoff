"""
Epistemic ledger: what each character already knows.

The failure it targets is "known-information forgetting" — a character re-asking or re-learning
something the story already told them. The ledger is explicit state; the prompt says "already
knows"; the check flags paragraphs that present a known fact as new.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set

NEWNESS = re.compile(
    r"\b(learned|realized|discovered|found out|for the first time|had no idea|never knew)\b",
    re.IGNORECASE,
)


@dataclass
class Violation:
    rule: str
    detail: str


@dataclass
class Ledger:
    knows: Dict[str, Set[str]] = field(default_factory=dict)
    scenes: Dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "Ledger":
        if not Path(path).is_file():
            return cls()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            knows={name: set(values) for name, values in (data.get("knows") or {}).items()},
            scenes=dict(data.get("scenes") or {}),
        )

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"knows": {name: sorted(values) for name, values in self.knows.items()},
                   "scenes": self.scenes}
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    def learn(self, character: str, fact: str, scene: str = "") -> None:
        self.knows.setdefault(character, set()).add(fact)
        if scene:
            self.scenes[scene] = len(self.knows[character])

    def check(self, character: str, text: str) -> List[Violation]:
        known = self.knows.get(character, set())
        lowered = text.lower()
        violations: List[Violation] = []
        if not NEWNESS.search(text):
            return violations
        for fact in known:
            keys = [word for word in re.findall(r"[a-z]+", fact.lower()) if len(word) > 3]
            if keys and sum(1 for key in keys if key in lowered) >= max(1, len(keys) // 2):
                violations.append(Violation("known_information_forgetting", fact))
        return violations

    def prompt_block(self, character: str) -> str:
        known = sorted(self.knows.get(character, set()))
        if not known:
            return ""
        return f"{character} already knows: " + "; ".join(known)
