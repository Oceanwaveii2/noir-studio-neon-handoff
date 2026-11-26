"""
Author-anchored voice block: guidance the model cannot copy from the books.

Sources:
  1. numeric style card (no text)
  2. the author's directions and AVOID lines for the beat
  3. up to three exemplar lines from the author's own corrected scene
  4. antislop negative constraints
  5. comedy mechanics stated as rules (no quotes)

No passage from `books/text` may enter this block. That is asserted by a test.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

from ..paths import asset, books
from .editorial import EditorialNotes
from .style_card import StyleCard

TONE_RULES = [
    "deadpan camp comedy: the narrator is unimpressed, never winking",
    "escalation in stages: let a beat sit before the next one lands",
    "dignity lost in pieces, not announced",
    "specific physical detail carries the joke; no summary narration",
    "understatement over exclamation",
]

MAX_EXEMPLARS = 3
_EXEMPLAR_SKIP = re.compile(r"^(?:\[|#|INT\.|EXT\.|Scene )", re.IGNORECASE)


def exemplars(limit: int = MAX_EXEMPLARS) -> List[str]:
    """Short action lines from the author's own corrected scene — not from the books."""
    scene = asset("work", "americandad", "start_scene_annotated.md")
    if not scene.is_file():
        return []
    lines = []
    for paragraph in scene.read_text(encoding="utf-8").split("\n\n"):
        text = paragraph.strip()
        if not text or _EXEMPLAR_SKIP.match(text):
            continue
        if text.startswith(("-", "\u2014", '"', "\u201c")):
            continue
        words = len(text.split())
        if 6 <= words <= 30:
            lines.append(text)
        if len(lines) >= limit:
            break
    return lines


def negative_constraints(limit: int = 10) -> List[str]:
    path = books("antislop.json")
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [entry[0] for entry in data.get("banlist", [])[:limit] if entry and entry[0]]


def block(beat_text: str = "") -> str:
    parts: List[str] = []
    card_path = books("style_card.json")
    if card_path.is_file():
        parts.append(StyleCard.load(card_path).prompt_block())

    notes = EditorialNotes.load()
    direction = notes.prompt_block(beat_text) if beat_text else ""
    if direction:
        parts.append(direction)

    lines = exemplars()
    if lines:
        parts.append(
            "AUTHOR EXEMPLARS (the author's own corrected lines; embody this register, cadence, and diction):\n"
            + "\n".join(f"- {line}" for line in lines)
        )

    banned = negative_constraints()
    if banned:
        parts.append("NEVER USE THESE PHRASES:\n" + ", ".join(banned))

    parts.append("COMEDY MECHANICS (rules, not quotes):\n" + "\n".join(f"- {rule}" for rule in TONE_RULES))
    return "\n\n".join(parts)
