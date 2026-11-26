"""
Editorial notes: the author's directions and rejected examples, as prompt material.

Loaded from books/editorial_notes.json. Each beat has:
  - direction: what the beat must do (from the author's notes)
  - avoid: lines the author marked bad (negative exemplars)

    python -m prose_engine voice notes --scene
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Beat:
    id: str
    match: str
    direction: str
    avoid: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    clips: List[str] = field(default_factory=list)


@dataclass
class EditorialNotes:
    scene: str
    beats: List[Beat]

    @classmethod
    def load(cls, path: str | Path | None = None) -> "EditorialNotes":
        from ..paths import books

        data = json.loads(Path(path or books("editorial_notes.json")).read_text(encoding="utf-8"))
        beats = [
            Beat(
                id=item.get("id", ""),
                match=item.get("match", ""),
                direction=item.get("direction", ""),
                avoid=list(item.get("avoid") or []),
                references=list(item.get("references") or []),
                clips=list(item.get("clips") or []),
            )
            for item in data.get("beats", [])
        ]
        return cls(scene=data.get("scene", "scene"), beats=beats)

    def for_text(self, text: str) -> Optional[Beat]:
        lowered = text.lower()
        for beat in self.beats:
            match = beat.match.lower()
            if match and match in lowered:
                return beat
        return None

    def prompt_block(self, text: str) -> str:
        beat = self.for_text(text)
        if beat is None:
            return ""
        lines = [f"SCENE DIRECTION (author's note for beat '{beat.id}'): {beat.direction}"]
        if beat.avoid:
            lines.append("NEVER WRITE LIKE THESE (the author rejected them):")
            lines.extend(f"- {item}" for item in beat.avoid)
        if beat.references:
            lines.append("TONE REFERENCES (actively draw upon their phrasing, rhythm, and diction):")
            lines.extend(f"- {item}" for item in beat.references)
        if beat.clips:
            from .clips import format_clips

            block = format_clips(beat.clips)
            if block:
                lines.append(block)
        return "\n".join(lines)
