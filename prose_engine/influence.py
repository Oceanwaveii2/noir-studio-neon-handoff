"""
Per-book influence control for the semantic drive.

Each reference book gets a level. The level controls how much of a retrieved reference set it
may occupy, independent of how many passages it contributes.

    off       0    excluded
    whisper   1    a rare share
    normal    2    the default
    strong    3    twice a normal book's share
    dominant  4    four times a normal book's share

Two modes:
    balanced   fair-share selection by level (a small book can outrank a big one)
    volume     score * level weight, so size still counts (the old behaviour, but tunable)

Stored in books/influence.json so the setting travels with the corpus.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

LEVEL_NAMES = ["off", "whisper", "normal", "strong", "dominant"]
LEVELS: Dict[str, int] = {name: index for index, name in enumerate(LEVEL_NAMES)}
WEIGHTS = {0: 0.0, 1: 0.25, 2: 1.0, 3: 2.0, 4: 4.0}
DEFAULT_LEVEL = 2
DEFAULT_MODE = "balanced"


@dataclass
class Influence:
    levels: Dict[str, int] = field(default_factory=dict)
    mode: str = DEFAULT_MODE
    path: Path | None = None

    def level_of(self, book: str) -> int:
        return self.levels.get(book, DEFAULT_LEVEL)

    def weight_of(self, book: str) -> float:
        return WEIGHTS.get(self.level_of(book), 1.0)

    def is_off(self, book: str) -> bool:
        return self.level_of(book) == 0

    def summary(self) -> List[Tuple[str, int, str, float]]:
        return [
            (book, level, LEVEL_NAMES[level], WEIGHTS[level])
            for book, level in sorted(self.levels.items())
        ]


def parse_level(value) -> int:
    if isinstance(value, int):
        if 0 <= value <= 4:
            return value
        raise ValueError(f"level out of range: {value}")
    text = str(value).strip().lower()
    if text.isdigit() and 0 <= int(text) <= 4:
        return int(text)
    if text in LEVELS:
        return LEVELS[text]
    raise ValueError(f"unknown level: {value!r} (use 0-4 or {', '.join(LEVEL_NAMES)})")


def load_influence(books_dir: str | Path = "books") -> Influence:
    path = Path(books_dir) / "influence.json"
    if not path.is_file():
        return Influence(path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    levels = {
        book: int(entry.get("level", DEFAULT_LEVEL)) if isinstance(entry, dict) else int(entry)
        for book, entry in (data.get("books") or {}).items()
    }
    mode = data.get("mode", DEFAULT_MODE)
    return Influence(levels=levels, mode=mode if mode in ("balanced", "volume") else DEFAULT_MODE, path=path)


def save_influence(influence: Influence) -> Path:
    path = influence.path or Path("books") / "influence.json"
    payload = {
        "mode": influence.mode,
        "books": {
            book: {"level": level, "name": LEVEL_NAMES[level]}
            for book, level in sorted(influence.levels.items())
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def select(
    scored: Sequence[Tuple[float, str, dict]],
    k: int,
    influence: Influence,
) -> List[Tuple[float, str, dict]]:
    """Picks k passages from score-ranked `scored` under the influence rules."""
    if k <= 0:
        return []

    by_book: Dict[str, List[Tuple[float, str, dict]]] = defaultdict(list)
    for item in scored:
        book = item[2].get("book", "?") if isinstance(item[2], dict) else "?"
        if influence.is_off(book):
            continue
        by_book[book].append(item)
    if not by_book:
        return []

    if influence.mode == "volume":
        ranked = sorted(
            (
                (item[0] * influence.weight_of(book), item)
                for book, items in by_book.items()
                for item in items
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        return [item for _, item in ranked[:k]]

    # Balanced: repeated fair-share pick. The next pick goes to the book with the highest
    # weight / (1 + picks so far), so equal levels rotate and stronger levels take more.
    picks: List[Tuple[float, str, dict]] = []
    counts: Dict[str, int] = defaultdict(int)
    while len(picks) < k:
        best_book = None
        best_key = -1.0
        for book, items in by_book.items():
            if not items:
                continue
            key = influence.weight_of(book) / (1 + counts[book])
            if key > best_key:
                best_key, best_book = key, book
        if best_book is None:
            break
        picks.append(by_book[best_book].pop(0))
        counts[best_book] += 1
    return picks


def describe(influence: Influence, titles: Dict[str, str] | None = None) -> str:
    lines = [f"mode: {influence.mode}"]
    for book, level, name, weight in influence.summary():
        title = (titles or {}).get(book, "")
        lines.append(f"  {book:<52} {name:<9} (level {level}, weight {weight:g})  {title}")
    return "\n".join(lines)
