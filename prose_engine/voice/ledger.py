"""
Fluent beat ledger.

Each beat declares what must already be true (`requires`) and what becomes true (`effects`),
as fluent strings: `at:Rainee:bathroom`, `prop:door:closed`, `knows:Haley:smell`,
`state:Rainee:dressed`.

The ledger walks the scene in order, applies effects, and reports:
  - a beat whose requirements are not met;
  - a plan beat that is missing from the scene;
  - a beat appearing twice.

    python -m prose_engine voice ledger --file work/americandad/start_scene_deepseek.md
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence

HEADING = re.compile(r"^(?:Scene \d+:.*|INT\..*|EXT\..*)$", re.MULTILINE)


@dataclass
class Beat:
    id: str
    match: str
    requires: List[str] = field(default_factory=list)
    effects: List[str] = field(default_factory=list)
    optional: bool = False


@dataclass
class BeatPlan:
    initial: List[str]
    beats: List[Beat]

    @classmethod
    def load(cls, path: str | Path | None = None) -> "BeatPlan":
        from ..paths import books

        data = json.loads(Path(path or books("editorial_notes.json")).read_text(encoding="utf-8"))
        beats = [
            Beat(
                id=item.get("id", ""),
                match=item.get("match", ""),
                requires=list(item.get("requires") or []),
                effects=list(item.get("effects") or []),
                optional=bool(item.get("optional", False)),
            )
            for item in data.get("beats", [])
        ]
        return cls(initial=list(data.get("initial") or []), beats=beats)

    def find(self, text: str) -> Beat | None:
        lowered = text.lower()
        for beat in self.beats:
            if beat.match and beat.match.lower() in lowered:
                return beat
        return None

    def requires_block(self, beat_id: str) -> str:
        beat = next((item for item in self.beats if item.id == beat_id), None)
        if beat is None:
            return ""
        lines = [f"BEAT '{beat.id}' REQUIREMENTS (true before this beat): " + (", ".join(beat.requires) or "none")]
        lines.append(f"BEAT '{beat.id}' MUST LEAVE TRUE: " + (", ".join(beat.effects) or "unchanged"))
        return "\n".join(lines)

    def validate(self, sections: Sequence[str]) -> Dict:
        state = set(self.initial)
        issues: List[str] = []
        seen: List[str] = []
        states: List[Dict] = []
        for section in sections:
            beat = self.find(section)
            if beat is None:
                continue
            if beat.id in seen:
                issues.append(f"beat '{beat.id}' appears twice")
            missing = [req for req in beat.requires if req not in state]
            if missing:
                issues.append(f"beat '{beat.id}' requires {missing} before it happens")
            state |= set(beat.effects)
            seen.append(beat.id)
            states.append({"beat": beat.id, "state": sorted(state)})
        for beat in self.beats:
            if beat.id not in seen and not beat.optional:
                issues.append(f"beat '{beat.id}' is missing from the scene")
        return {"issues": issues, "states": states, "final": sorted(state)}


def sections(text: str) -> List[str]:
    matches = list(HEADING.finditer(text))
    if not matches:
        return [text.strip()]
    parts = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        parts.append(text[match.start():end].strip())
    return parts
