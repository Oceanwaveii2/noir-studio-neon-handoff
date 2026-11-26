"""
Screenplay-aware chunking.

Blank lines are not paragraphs. A dialogue block is a cue, its parentheticals, and its lines; a
scene is a heading plus its opening action. Single lines are merged into their neighbours so the
workbench never shows "**RAINEE**" as a passage of its own.
"""

from __future__ import annotations

import re
from typing import List

SCENE = re.compile(r"^(INT|EXT)\.", re.IGNORECASE)
CUE_BOLD = re.compile(r"^\*\*[A-Z][A-Z0-9 .'\-]{0,40}\*\*$")
CUE_PLAIN = re.compile(r"^[A-Z][A-Z0-9 .'\-]{1,40}$")
PAREN = re.compile(r"^\*?\(.*\)\*?$")
DIALOGUE = re.compile(r"^[-—]")

MIN_CHARS = 60


def classify(block: str) -> str:
    block = block.strip()
    if SCENE.match(block):
        return "scene"
    if CUE_BOLD.match(block) or CUE_PLAIN.match(block):
        return "cue"
    if PAREN.match(block):
        return "parenthetical"
    if DIALOGUE.match(block):
        return "dialogue"
    return "action"


def _join(blocks: List[str]) -> str:
    return "\n\n".join(blocks).strip()


def chunk_text(text: str, min_chars: int = MIN_CHARS) -> List[str]:
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    chunks: List[str] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        kind = classify(block)

        if kind == "scene":
            group = [block]
            index += 1
            if index < len(blocks) and classify(blocks[index]) == "action":
                group.append(blocks[index])
                index += 1
            chunks.append(_join(group))
            continue

        if kind == "cue":
            group = [block]
            index += 1
            while index < len(blocks) and classify(blocks[index]) in ("parenthetical", "dialogue"):
                group.append(blocks[index])
                index += 1
            chunks.append(_join(group))
            continue

        if kind == "dialogue":
            group = [block]
            index += 1
            while index < len(blocks) and classify(blocks[index]) == "dialogue":
                group.append(blocks[index])
                index += 1
            chunks.append(_join(group))
            continue

        # action (or stray parenthetical): one paragraph; short ones merge below
        chunks.append(block)
        index += 1

    merged: List[str] = []
    for chunk in chunks:
        if merged and len(chunk) < min_chars and classify(merged[-1].splitlines()[0]) not in ("scene", "cue"):
            merged[-1] = merged[-1] + "\n\n" + chunk
        else:
            merged.append(chunk)
    return merged


def label(chunk: str) -> str:
    """Short label for the workbench header."""
    first = chunk.splitlines()[0].strip()
    kind = classify(first)
    if kind == "scene":
        return first[:70]
    if kind == "cue":
        return first.strip("*").strip() + " · dialogue"
    if kind == "dialogue":
        return "dialogue"
    first = chunk.splitlines()[0].strip()
    return first[:64] + ("…" if len(first) > 64 else "")
