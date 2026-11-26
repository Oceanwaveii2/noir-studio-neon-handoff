"""
Scene contract: the beat a paragraph must serve.

Kept deliberately small — pov, setting, beat, required facts, forbidden facts, and the state the
scene must leave behind. Checked after rewriting; never asked of the model.
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
class Contract:
    scene_id: str
    pov: str = ""
    setting: str = ""
    beat: str = ""
    facts: List[str] = field(default_factory=list)
    forbidden: List[str] = field(default_factory=list)
    state_in: Dict[str, str] = field(default_factory=dict)
    state_out: Dict[str, str] = field(default_factory=dict)
    future_beats: List[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "Contract":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**{key: data[key] for key in data if key in cls.__dataclass_fields__})

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.__dict__, indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    def check(self, paragraph: str) -> List[Violation]:
        lowered = paragraph.lower()
        violations: List[Violation] = []
        for fact in self.facts:
            if fact.lower() not in lowered:
                violations.append(Violation("missing_fact", fact))
        for phrase in self.forbidden:
            if phrase.lower() in lowered:
                violations.append(Violation("forbidden", phrase))
        if self.pov and self.pov.lower() not in lowered and self.pov != "narrator":
            violations.append(Violation("pov_absent", self.pov))
        return violations

    def prompt_block(self) -> str:
        lines = [f"SCENE CONTRACT ({self.scene_id})"]
        if self.setting:
            lines.append(f"setting: {self.setting}")
        if self.pov:
            lines.append(f"pov: {self.pov}")
        if self.beat:
            lines.append(f"beat: {self.beat}")
        if self.facts:
            lines.append("required facts: " + "; ".join(self.facts))
        if self.forbidden:
            lines.append("forbidden: " + "; ".join(self.forbidden))
        if self.state_out:
            lines.append(
                "state at scene end: "
                + "; ".join(f"{name}={value}" for name, value in self.state_out.items())
            )
        if self.future_beats:
            lines.append("later: " + "; ".join(self.future_beats))
        return "\n".join(lines)
