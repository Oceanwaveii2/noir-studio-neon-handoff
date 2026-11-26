"""
Contrastive exemplars: show the model what NOT to sound like.

Negative examples come from the project's own AI drafts, each tagged with the tic it demonstrates.
They are appended to the conditioning prompt only when the paragraph's warnings match the tic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

_DATA = Path(__file__).resolve().parent / "data" / "ai_voice_negatives.json"

_TRIGGERS = {
    "Simile pileup": "simile pileup",
    "Filter words": "filter words",
    "Emotion label": "emotion label",
    "Monotonous cadence": "summary narration",
    "Beat": "beat cue",
}


def load_negatives() -> List[Dict]:
    return json.loads(_DATA.read_text(encoding="utf-8"))


def select(warnings: List[str], limit: int = 2) -> List[Dict]:
    """Picks negatives whose tic matches the warnings; falls back to none."""
    wanted: List[str] = []
    for warning in warnings:
        for key, tic in _TRIGGERS.items():
            if key.lower() in warning.lower() and tic not in wanted:
                wanted.append(tic)
    negatives = load_negatives()
    chosen = [item for tic in wanted for item in negatives if item["tic"] == tic]
    return chosen[:limit]


def block(negatives: List[Dict]) -> str:
    if not negatives:
        return ""
    lines = ["DO NOT IMITATE THESE (AI tells; each is a failure mode):"]
    for item in negatives:
        lines.append(f'- [{item["tic"]}] "{item["text"]}"')
        lines.append(f'  why: {item["why"]}')
    lines.append("Write none of this. Every sentence you return must be written from the facts.")
    return "\n".join(lines)
