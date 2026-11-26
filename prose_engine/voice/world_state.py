"""
World state: the rules a scene may not break.

Loaded from books/world_state.json. Two jobs:
  - prompt_block() puts the canon in front of the model
  - violations(text) catches canon breaks in generated or existing text

    python -m prose_engine voice world --file scene.md
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class WorldState:
    title: str = "world"
    rules: List[str] = field(default_factory=list)
    characters: Dict[str, dict] = field(default_factory=dict)
    banned: List[dict] = field(default_factory=list)
    props: Dict[str, str] = field(default_factory=dict)
    impossible: List[dict] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "WorldState":
        from ..paths import books

        data = json.loads(Path(path or books("world_state.json")).read_text(encoding="utf-8"))
        return cls(
            title=data.get("title", "world"),
            rules=list(data.get("rules") or []),
            characters=dict(data.get("characters") or {}),
            banned=list(data.get("banned") or []),
            props=dict(data.get("props") or {}),
            impossible=list(data.get("impossible") or []),
        )

    def prompt_block(self) -> str:
        lines = [f"WORLD STATE — {self.title} (hard canon; never contradict it)"]
        lines += [f"- {rule}" for rule in self.rules]
        for name, data in self.characters.items():
            role = data.get("role", "")
            aliases = ", ".join(data.get("aliases", []))
            lines.append(f"- {name}: {role}" + (f" (aliases: {aliases})" if aliases else ""))
        for name, note in self.props.items():
            lines.append(f"- {name}: {note} (allowed, not an error)")
        if self.impossible:
            lines.append("NOT POSSIBLE HERE:")
            seen = set()
            for item in self.impossible:
                why = item.get("why", "")
                if why and why not in seen:
                    seen.add(why)
                    lines.append(f"- {why}")
        return "\n".join(lines)

    def violations(self, text: str) -> List[Tuple[str, str]]:
        from ..canon_rules import find_rule_violations

        return [
            (matched, str(rule.get("why", "breaks canon")))
            for rule, matched in find_rule_violations(text, self.banned)
        ]

    def plausibility(self, text: str) -> List[Tuple[str, str]]:
        """Contextual impossibilities (narrative logic), respecting negations and quote context."""
        from ..canon_rules import DEFAULT_NEGATION_CUES, is_negated, sentence_window

        found: List[Tuple[str, str]] = []
        for item in self.impossible:
            pattern = item.get("pattern", "")
            if not pattern:
                continue
            allow_context = [c.lower() for c in item.get("allow_context", ())]
            cues = item.get("negation_cues", DEFAULT_NEGATION_CUES)
            for match in re.finditer(pattern, text, re.IGNORECASE):
                window = sentence_window(text, match.start(), match.end()).lower()
                if allow_context and any(c in window for c in allow_context):
                    continue
                if item.get("allow_negated", True) and is_negated(text, match, cues):
                    continue
                found.append((match.group(0)[:80], item.get("why", "not possible here")))
                break
        return found

    def check(self, text: str) -> bool:
        return not self.violations(text) and not self.plausibility(text)
