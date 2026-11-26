"""
Typed story bible: entities, immutable traits, forbidden claims, props, facts.

This is the structured half of continuity. The rules are deliberately narrow: appearance
invariants, forbidden claims, prop possession, and facts that may not disappear.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


@dataclass
class Violation:
    rule: str
    detail: str


@dataclass
class Character:
    traits: List[str] = field(default_factory=list)
    forbidden_claims: List[str] = field(default_factory=list)


@dataclass
class Prop:
    held_by: str = ""
    since: int = 0


@dataclass
class Bible:
    characters: Dict[str, Character] = field(default_factory=dict)
    props: Dict[str, Prop] = field(default_factory=dict)
    facts: List[str] = field(default_factory=list)
    locations: Dict[str, List[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "Bible":
        if not Path(path).is_file():
            return cls()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            characters={
                name: Character(**value) for name, value in (data.get("characters") or {}).items()
            },
            props={name: Prop(**value) for name, value in (data.get("props") or {}).items()},
            facts=list(data.get("facts") or []),
            locations=dict(data.get("locations") or {}),
        )

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "characters": {name: char.__dict__ for name, char in self.characters.items()},
            "props": {name: prop.__dict__ for name, prop in self.props.items()},
            "facts": self.facts,
            "locations": self.locations,
        }
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    def check(self, text: str) -> List[Violation]:
        lowered = text.lower()
        violations: List[Violation] = []
        for name, character in self.characters.items():
            for claim in character.forbidden_claims:
                if claim.lower() in lowered:
                    violations.append(Violation("forbidden_claim", f"{name}: {claim}"))
        return violations

    def diff(self, before: str, after: str) -> List[Violation]:
        """Facts named in the original that disappeared in the rewrite."""
        lowered = after.lower()
        return [
            Violation("lost_fact", fact)
            for fact in self.facts
            if fact.lower() in before.lower() and fact.lower() not in lowered
        ]

    def prompt_block(self) -> str:
        lines = ["STORY BIBLE"]
        for name, character in self.characters.items():
            line = f"{name}: traits={', '.join(character.traits) or 'none'}"
            if character.forbidden_claims:
                line += f"; never: {', '.join(character.forbidden_claims)}"
            lines.append(line)
        for name, prop in self.props.items():
            lines.append(f"prop {name}: held by {prop.held_by} from scene {prop.since}")
        for location, exits in self.locations.items():
            lines.append(f"{location} exits: {', '.join(exits)}")
        if self.facts:
            lines.append("facts: " + "; ".join(self.facts))
        return "\n".join(lines)
