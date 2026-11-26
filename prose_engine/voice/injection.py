"""
Active Stylistic Injection Engine.

Mines and injects signature author idioms, metaphor domains, and rhythmic cadences
from the 10-book reference corpus and dance-pop lyrics into prompt attention.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Dict, List, Optional

_CACHED_BANKS: Optional[Dict] = None


def get_idiom_banks_path() -> Path:
    from ..paths import books
    return books("idiom_banks.json")


def load_all_banks() -> Dict:
    global _CACHED_BANKS
    if _CACHED_BANKS is not None:
        return _CACHED_BANKS
    path = get_idiom_banks_path()
    if path.is_file():
        _CACHED_BANKS = json.loads(path.read_text(encoding="utf-8"))
    else:
        _CACHED_BANKS = {"lenses": {}}
    return _CACHED_BANKS


def get_lens_bank(lens_id: str) -> Dict:
    banks = load_all_banks()
    lenses = banks.get("lenses", {})
    key = lens_id.lower().strip()
    if key in lenses:
        return lenses[key]
    for lid, data in lenses.items():
        if key in lid or key in data.get("author", "").lower():
            return data
    return lenses.get("irby", {})


def sample_idioms(lens_id: str, count: int = 4, seed: Optional[int] = None) -> List[str]:
    """Sample signature idioms from the given author lens."""
    bank = get_lens_bank(lens_id)
    idioms = bank.get("idioms", [])
    if not idioms:
        return []
    rng = random.Random(seed) if seed is not None else random
    k = min(count, len(idioms))
    return rng.sample(idioms, k)


def sample_rhythm(lens_id: str, seed: Optional[int] = None) -> str:
    """Sample a rhythmic cadence instruction from the given author lens."""
    bank = get_lens_bank(lens_id)
    patterns = bank.get("rhythmic_patterns", [])
    if not patterns:
        return "Mix short punchy sentences with longer descriptive clauses."
    rng = random.Random(seed) if seed is not None else random
    return rng.choice(patterns)


def format_injection_prompt(lens_id: str, count: int = 3, seed: Optional[int] = None) -> str:
    """Formats an active stylistic injection block for inclusion in writer prompts."""
    bank = get_lens_bank(lens_id)
    if not bank:
        return ""
    author = bank.get("author", "Reference Author")
    mandate = bank.get("style_mandate", "")
    idioms = sample_idioms(lens_id, count=count, seed=seed)
    rhythm = sample_rhythm(lens_id, seed=seed)
    sensory = ", ".join(bank.get("sensory_focus", []))

    lines = [
        f"=== ACTIVE STYLISTIC INJECTION ({author.upper()}) ===",
        f"STYLE MANDATE: {mandate}",
        f"RHYTHMIC CADENCE: {rhythm}",
    ]
    if sensory:
        lines.append(f"SENSORY FOCUS: {sensory}")
    if idioms:
        lines.append("\nSIGNATURE IDIOMS & TURNS OF PHRASE (ACTIVELY BORROW & WEAVE THESE IN):")
        for idiom in idioms:
            lines.append(f'- "{idiom}"')
    lines.append(
        "\nDIRECTIVE: You are explicitly directed to borrow, adapt, and weave these distinctive turns of phrase, "
        "rhythmic cadences, and metaphor patterns into your descriptive sentences. Do not default to safe, generic AI prose."
    )
    return "\n".join(lines)


def calculate_borrow_rate(text: str, lens_id: str) -> float:
    """Calculates the proportion of target author signature idioms or keywords found in text."""
    bank = get_lens_bank(lens_id)
    idioms = bank.get("idioms", [])
    if not idioms:
        return 0.0
    lowered = text.lower()
    matches = 0
    for idiom in idioms:
        words = idiom.lower().split()
        # Match if at least a 2-word collocation from the idiom appears in text
        if len(words) >= 2:
            bigrams = [" ".join(words[i:i+2]) for i in range(len(words)-1)]
            if any(bg in lowered for bg in bigrams):
                matches += 1
    return round(matches / max(1, len(idioms)), 4)
