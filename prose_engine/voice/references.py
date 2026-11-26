"""Reference passages as a prompt block (shared by every generation path)."""

from __future__ import annotations

from typing import Sequence


def format_references(texts: Sequence[str], title: str = "VOICE REFERENCES from the books") -> str:
    """The block every rewrite path must carry when retrieval is enabled."""
    cleaned = [text.strip() for text in texts if text and text.strip()]
    if not cleaned:
        return ""
    lines = [f"{title} (actively borrow and adapt their rhythm, diction, metaphors, and sentence shapes):"]
    lines.extend(f"- {text}" for text in cleaned)
    return "\n".join(lines)
