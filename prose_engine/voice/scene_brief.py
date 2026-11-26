"""
Scene brief: the simple contract between the writer and the engine.

    {"events": ["Rainee farts", "nanites surge to her hips", ...],
     "dialogue": [{"text": "- Don't body-shame the masterpiece.", "keep": true}, ...],
     "strength": 0.85,
     "treatments": ["curse", "staged"]}

Kept dialogue is frozen verbatim; dropped dialogue may be cut or absorbed. Events drive the
variation engine. Strength sets the default per-passage rewrite policy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Sequence

DIALOGUE_PREFIX = ("-", "—", "“", '"')


@dataclass
class DialogueItem:
    text: str
    keep: bool = True


@dataclass
class SceneBrief:
    events: List[str] = field(default_factory=list)
    dialogue: List[DialogueItem] = field(default_factory=list)
    strength: float = 0.85
    treatments: List[str] = field(default_factory=list)
    title: str = "scene"
    tone: str = ""

    @classmethod
    def load(cls, path: str | Path) -> "SceneBrief":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            events=list(data.get("events") or []),
            dialogue=[
                DialogueItem(text=item["text"], keep=bool(item.get("keep", True)))
                for item in (data.get("dialogue") or [])
                if item.get("text")
            ],
            strength=float(data.get("strength", 0.85)),
            treatments=list(data.get("treatments") or []),
            title=data.get("title", "scene"),
            tone=data.get("tone", ""),
        )

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "title": self.title,
            "events": self.events,
            "dialogue": [asdict(item) for item in self.dialogue],
            "strength": self.strength,
            "treatments": self.treatments,
            "tone": self.tone,
        }
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    @classmethod
    def from_text(cls, text: str, title: str = "scene") -> "SceneBrief":
        paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
        dialogue = [
            DialogueItem(text=part, keep=True)
            for part in paragraphs
            if part.startswith(DIALOGUE_PREFIX)
        ]
        return cls(dialogue=dialogue, title=title)

    def kept(self) -> List[str]:
        return [item.text for item in self.dialogue if item.keep]

    def dropped(self) -> List[str]:
        return [item.text for item in self.dialogue if not item.keep]

    def frozen(self) -> List[str]:
        return self.kept()

    def prompt_block(self) -> str:
        lines = [f"SCENE BRIEF — {self.title}"]
        if self.tone:
            lines.append("TONE: " + self.tone)
        if self.events:
            lines.append("EVENTS (all must happen):")
            lines.extend(f"{number}. {event}" for number, event in enumerate(self.events, 1))
        if self.kept():
            lines.append("KEEP VERBATIM (dialogue):")
            lines.extend(f"- {line}" for line in self.kept())
        if self.dropped():
            lines.append("THESE LINES MAY BE CUT OR REWRITTEN:")
            lines.extend(f"- {line}" for line in self.dropped())
        lines.append(f"REWRITE STRENGTH: {self.strength:.2f}")
        return "\n".join(lines)


def dialogue_from_paragraphs(paragraphs: Sequence[str]) -> List[DialogueItem]:
    return [
        DialogueItem(text=part.strip(), keep=True)
        for part in paragraphs
        if part.strip().startswith(DIALOGUE_PREFIX)
    ]
